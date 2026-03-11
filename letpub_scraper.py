"""
JournalFlow - LetPub 期刊经验分享爬虫模块
=========================================
完整流程：输入期刊名称 → 自动搜索 ID → 抓取经验分享评论

依赖：requests, beautifulsoup4
安装：pip install requests beautifulsoup4
"""

import re
import time
import json
import random
import requests
from bs4 import BeautifulSoup
from typing import List, Optional, Dict
from difflib import SequenceMatcher


# ============================================================
# ▼ 在此填入你从浏览器 DevTools → Network → Cookie 复制的完整 Cookie 字符串
# ============================================================
MY_COOKIE = "请替换为你的真实Cookie字符串"
# 示例：MY_COOKIE = "PHPSESSID=abc123; letpub_user=yourname; ..."
# ============================================================

# --- 常用 User-Agent 池，每次请求随机选取 ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

LETPUB_SEARCH_URL = "https://www.letpub.com.cn/index.php"
LETPUB_DETAIL_BASE = "https://www.letpub.com.cn/index.php?page=journalapp&view=detail&journalid="


# ================================================================
# 工具函数
# ================================================================

def _build_headers(cookie: str = "", referer: str = "https://www.letpub.com.cn/") -> dict:
    """构造带随机 UA 的请求头，cookie 为空时不附加（搜索接口可不需要登录）"""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度（0~1），用于模糊匹配期刊名"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ================================================================
# 第一步：期刊名 → 搜索 → 返回候选期刊列表
# ================================================================

def search_journal(
    journal_name: str,
    cookie: str = "",
    top_n: int = 5,
) -> List[Dict]:
    """
    通过期刊名搜索 LetPub，返回最匹配的候选期刊列表。

    LetPub 提供两个可用入口，按优先级尝试：
      入口A（推荐）：AJAX 搜索接口，返回 JSON，直接包含 journalid
      入口B（备用）：HTML 搜索结果页，解析 <a> 链接提取 journalid

    参数
    ----
    journal_name : 期刊名称，支持英文全称 / 缩写 / 关键词
                   示例："Nature"、"AAAI"、"IEEE Transactions on Neural"
    cookie       : 可选，搜索接口通常不需要登录
    top_n        : 返回前 N 个候选结果（默认 5）

    返回
    ----
    List[Dict]，每项包含：
      {
        "journal_id":  "1234",          # LetPub 内部期刊 ID
        "full_name":   "Nature",        # 期刊全名
        "issn":        "0028-0836",     # ISSN
        "detail_url":  "https://...",   # 详情页 URL（直接传给 get_letpub_comments）
        "similarity":  0.95,            # 与输入名称的相似度（0~1）
      }
    """
    results = []

    # ── 入口A：AJAX JSON 接口 ────────────────────────────────────────
    # LetPub 搜索框背后调用此接口（通过 DevTools 抓包确认），返回 JSON
    try:
        params = {
            "page": "journalapp",
            "view": "search",
            "searchname": journal_name,
            "searchissn": "",
            "searchfield": "",
            "searchimpactlow": "",
            "searchimpacthigh": "",
            "searchsci": "",
            "searchhjindex": "",
            "typejn": "1",
            "displayJnlType": "ALL",
            "format": "json",
        }
        headers = _build_headers(cookie)
        headers["X-Requested-With"] = "XMLHttpRequest"   # 标记为 XHR
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"

        resp = requests.get(LETPUB_SEARCH_URL, params=params, headers=headers, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()

        # JSON 结构兼容多种格式：{"aaData": [...]} 或 {"data": [...]} 或直接是列表
        rows = (
            data.get("aaData")
            or data.get("data")
            or (data if isinstance(data, list) else [])
        )

        for row in rows:
            if isinstance(row, list) and len(row) >= 2:
                jid  = str(row[0]).strip()
                name = str(row[1]).strip()
                issn = str(row[2]).strip() if len(row) > 2 else ""
            elif isinstance(row, dict):
                jid  = str(row.get("id") or row.get("journalid") or "").strip()
                name = str(row.get("name") or row.get("full_name") or "").strip()
                issn = str(row.get("issn") or "").strip()
            else:
                continue

            if not jid or not jid.isdigit():
                continue

            results.append({
                "journal_id": jid,
                "full_name":  name,
                "issn":       issn,
                "detail_url": LETPUB_DETAIL_BASE + jid,
                "similarity": _similarity(journal_name, name),
            })

        print(f"[JournalFlow] 入口A搜索 '{journal_name}'：找到 {len(results)} 条候选")

    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"[JournalFlow] 入口A失败（{e}），切换到入口B解析 HTML...")
        results = []

    # ── 入口B（备用）：解析 HTML 搜索结果页 ─────────────────────────
    if not results:
        try:
            params = {
                "page": "journalapp",
                "view": "search",
                "searchname": journal_name,
                "typejn": "1",
                "displayJnlType": "ALL",
            }
            resp = requests.get(
                LETPUB_SEARCH_URL, params=params,
                headers=_build_headers(cookie), timeout=15
            )
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            # 搜索结果表格：期刊名是 <a href="...journalid=XXXX..."> 链接
            for a_tag in soup.find_all("a", href=re.compile(r"journalid=(\d+)")):
                match = re.search(r"journalid=(\d+)", a_tag["href"])
                if not match:
                    continue
                jid  = match.group(1)
                name = a_tag.get_text(strip=True)

                if any(r["journal_id"] == jid for r in results):  # 去重
                    continue

                # 同行 <td> 里提取 ISSN
                issn = ""
                parent_tr = a_tag.find_parent("tr")
                if parent_tr:
                    for td in parent_tr.find_all("td"):
                        text = td.get_text(strip=True)
                        if re.match(r"\d{4}-\d{3}[\dXx]", text):
                            issn = text
                            break

                results.append({
                    "journal_id": jid,
                    "full_name":  name,
                    "issn":       issn,
                    "detail_url": LETPUB_DETAIL_BASE + jid,
                    "similarity": _similarity(journal_name, name),
                })

            print(f"[JournalFlow] 入口B搜索 '{journal_name}'：找到 {len(results)} 条候选")

        except requests.RequestException as e:
            print(f"[JournalFlow] 入口B也失败：{e}")

    # 按相似度降序排列，返回前 top_n 条
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_n]


def pick_best_journal(candidates: List[Dict], journal_name: str) -> Optional[Dict]:
    """
    从候选列表中自动选出最佳匹配的期刊并给出提示。

    相似度 >= 0.85 → 静默自动选取
    相似度 0.5~0.85 → 打印候选列表后选最高分
    相似度 < 0.5   → 警告可能匹配不准，仍返回最高分
    """
    if not candidates:
        print(f"[JournalFlow] ✗ 未找到与 '{journal_name}' 相关的期刊，请检查拼写")
        return None

    best = candidates[0]

    if best["similarity"] >= 0.85:
        print(f"[JournalFlow] ✓ 自动匹配：{best['full_name']}（ID: {best['journal_id']}，相似度: {best['similarity']:.0%}）")
        return best

    # 相似度较低时，打印所有候选供用户核查
    print(f"\n[JournalFlow] 搜索 '{journal_name}' 的候选结果（相似度排序）：")
    print("-" * 72)
    for i, j in enumerate(candidates, 1):
        marker = "◀ 自动选取" if i == 1 else ""
        print(f"  {i}. [{j['journal_id']:>6}]  {j['full_name']:<48} {j['similarity']:.0%}  {marker}")
    print("-" * 72)

    if best["similarity"] >= 0.5:
        print(f"[JournalFlow] 已选取相似度最高结果。若不正确，请修改 journal_name 或在代码中")
        print(f"[JournalFlow] 改用 get_letpub_comments(LETPUB_DETAIL_BASE + '期刊ID', ...) 直接指定")
    else:
        print(f"[JournalFlow] ⚠ 相似度偏低（{best['similarity']:.0%}），建议核实期刊名称后重试")

    return best


# ================================================================
# 第二步：根据期刊详情页 URL 抓取经验分享评论
# ================================================================

def _is_login_blocked(html: str) -> bool:
    """
    精准判断"评论区"是否被登录墙拦截，避免误判导航栏中的"请登录"文字。

    LetPub 未登录时拦截评论的特征（任意一条命中即返回 True）：
      1. 页面含密码输入框 <input type="password">（典型登录表单）
      2. 评论容器内部出现登录提示（精确定位到注释区）
      3. 页面正文字数极少（< 200字）且含登录关键词（整页被替换成登录页）
    """
    soup = BeautifulSoup(html, "html.parser")

    # 特征1：页面含登录表单（有 password 输入框）
    if soup.find("input", {"type": "password"}):
        return True

    # 特征2：评论容器内部出现登录提示
    comment_area = (
        soup.find(id=re.compile(r"(user_review|experience|comment|review)", re.I))
        or soup.find(class_=re.compile(r"(user_review|experience|comment_list|review)", re.I))
    )
    if comment_area:
        area_text = comment_area.get_text()
        if any(kw in area_text for kw in ["请登录", "登录后", "login to view", "需要登录"]):
            return True

    # 特征3：全页正文极短，且含登录关键词（说明被重定向到纯登录页）
    body = soup.find("body")
    body_text = body.get_text(strip=True) if body else html
    if len(body_text) < 200 and any(
        kw in body_text for kw in ["请登录", "用户登录", "login", "sign in"]
    ):
        return True

    return False


def _debug_hint(html: str) -> None:
    """
    当第1页解析结果为 0 条时，自动输出诊断信息帮助排查。
    打印页面标题、评论容器识别情况、HTML 关键片段。
    """
    soup = BeautifulSoup(html, "html.parser")
    print("\n" + "─" * 60)
    print("[JournalFlow][调试] 第1页解析到 0 条，输出诊断信息：")

    # 页面标题
    title = soup.find("title")
    print(f"  页面标题  : {title.get_text(strip=True) if title else '(未找到)'}")

    # 导航栏/用户区域文字（判断是否真的已登录）
    nav_text = " ".join(
        tag.get_text(strip=True)
        for tag in soup.find_all(
            ["div", "span", "a"],
            class_=re.compile(r"(user|account|login|nav|member)", re.I)
        )
    )
    print(f"  导航栏文字: {nav_text[:150]}")

    # 评论容器
    container = (
        soup.find(id=re.compile(r"(user_review|experience|comment|review)", re.I))
        or soup.find(class_=re.compile(r"(user_review|experience|comment_list)", re.I))
    )
    if container:
        preview = container.get_text(separator=" ", strip=True)[:300]
        print(f"  评论容器  : ✓ 找到（{container.get('class') or container.get('id')}）")
        print(f"  容器内容  : {preview}...")
    else:
        print("  评论容器  : ✗ 未找到，需要更新解析规则（见下方说明）")

    # 页面所有表格数量
    tables = soup.find_all("table")
    print(f"  页面表格数: {len(tables)}")
    if tables:
        first_tr = tables[0].find("tr")
        if first_tr:
            print(f"  首行内容  : {first_tr.get_text(separator=' | ', strip=True)[:200]}")

    print("─" * 60)
    print("[JournalFlow][调试] → 请在浏览器打开期刊URL，F12 查看评论区父元素的")
    print("[JournalFlow][调试]   class 或 id，然后补充到代码 _parse_comments_from_html")
    print("[JournalFlow][调试]   的策略1（keyword列表）或策略2（re.compile 模式）中\n")


def _parse_comments_from_html(html: str) -> List[Dict]:
    """
    从单页 HTML 精准解析 LetPub 投稿经验，返回结构化字典列表。

    ━━━ 真实 DOM 结构（已通过源码确认）━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    评论列表容器：<ul class="flow-default" id="LAY_demo123">
    每条评论单元：<div class="grid-demo">
      ├─ <strong>#136楼</strong>                        ← 楼层号
      ├─ <a href="/profile/xxx">rabblf</a>              ← 作者昵称
      ├─ <div style="color:#FF5722...">10.0</div>       ← 评分数值
      ├─ <span class="layui-badge layui-bg-gray">       ← 研究方向标签（多个）
      ├─ <strong>投稿结果：</strong>已投修改后录用       ← 各元数据字段
      ├─ <strong>投稿周期：</strong>2.0 个月
      ├─ <strong>发表时间：</strong>2026-02-26 22:22:35
      └─ <blockquote class="layui-elem-quote">          ← 经验正文
           <b>投稿经验：</b><br>
           [正文内容，含 <br> 换行]
           <div id="reply_section_wrapper_XXX">         ← 回复区（需剔除）
             <blockquote class="layui-quote-nm">...
           </div>
         </blockquote>
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    返回字段：floor / author / rating / direction /
              result / period / pub_date / experience / comment_id
    """
    soup = BeautifulSoup(html, "html.parser")
    records: List[Dict] = []

    # 定位所有评论块：每条评论是 <div class="grid-demo">
    blocks = soup.find_all("div", class_="grid-demo")
    if not blocks:
        return records

    for block in blocks:
        # ── 楼层号：<strong>#136楼</strong> ─────────────────────────
        floor = ""
        floor_tag = block.find("strong", string=re.compile(r"#\d+楼"))
        if floor_tag:
            m = re.search(r"#(\d+)楼", floor_tag.get_text())
            if m:
                floor = m.group(1)
        if not floor:
            continue  # 没有楼层号说明不是评论块，跳过

        # ── 作者昵称：第一个 /profile/ 链接 ─────────────────────────
        author = ""
        author_tag = block.find("a", href=re.compile(r"/profile/"))
        if author_tag:
            author = author_tag.get_text(strip=True)

        # ── 期刊评分：color:#FF5722 的 div，内容是纯数字如 "10.0" ────
        # DOM: <div style="...color:#FF5722; font-weight:bold;">10.0</div>
        rating = ""
        for div in block.find_all("div", style=re.compile(r"color:#FF5722")):
            txt = div.get_text(strip=True)
            if re.fullmatch(r"\d+\.?\d*", txt):
                rating = txt
                break

        # ── 研究方向：多个 layui-badge layui-bg-gray span ────────────
        direction_tags = block.find_all(
            "span",
            class_=lambda c: c and "layui-badge" in c and "layui-bg-gray" in c
        )
        direction = " / ".join(t.get_text(strip=True) for t in direction_tags)

        # ── 元数据字段：<strong>标签：</strong> 文字 ─────────────────
        # DOM: <span><strong>投稿结果：</strong>已投修改后录用</span>
        def get_labeled_field(label: str) -> str:
            """找到含 label 文字的 <strong>，返回其父元素去掉 label 后的文字"""
            strong = block.find("strong", string=label)
            if not strong:
                return ""
            parent_text = strong.parent.get_text(strip=True)
            return parent_text.replace(label, "").strip()

        result   = get_labeled_field("投稿结果：")
        period   = get_labeled_field("投稿周期：")
        pub_date = get_labeled_field("发表时间：")

        # ── 投稿经验正文：<blockquote class="layui-elem-quote"> ───────
        # 步骤：① 找主 blockquote（含 <b>投稿经验：</b>）
        #        ② 先删掉嵌套的 reply_section_wrapper div（其中含子回复）
        #        ③ 再提取文本，去掉 "投稿经验：" 前缀
        experience = ""
        comment_id = ""

        main_bq = None
        for bq in block.find_all("blockquote", class_="layui-elem-quote"):
            # 只选含"投稿经验"的主 blockquote（排除子回复 blockquote）
            if bq.find("b", string="投稿经验："):
                main_bq = bq
                break

        if main_bq:
            # ── ① 提取 comment_id ────────────────────────────────────
            author_followups = []
            reply_div = main_bq.find("div", id=re.compile(r"reply_section_wrapper_(\d+)"))
            if reply_div:
                m2 = re.search(r"reply_section_wrapper_(\d+)", reply_div.get("id", ""))
                if m2:
                    comment_id = m2.group(1)

                # ── ② 提取作者本人的追加回复（过滤他人回复）─────────
                # 结构：<blockquote class="layui-elem-quote layui-quote-nm">
                #         【<a href="/profile/xxx">author</a>】 发表时间：XXXX
                #         <br>追加内容
                #       </blockquote>
                for sub_bq in reply_div.find_all(
                    "blockquote",
                    class_=lambda c: c and "layui-quote-nm" in c
                ):
                    sub_author_tag = sub_bq.find("a", href=re.compile(r"/profile/"))
                    if not sub_author_tag:
                        continue
                    if sub_author_tag.get_text(strip=True) != author:
                        continue  # 他人回复，跳过
                    # 先删除右侧按钮栏（点赞/主页/好友），避免混入文字
                    for toolbar in sub_bq.find_all(
                        "span", style=re.compile(r"float\s*:\s*right")
                    ):
                        toolbar.decompose()
                    raw = sub_bq.get_text(separator="\n", strip=True)
                    cleaned = re.sub(
                        r"^【[^】]*】\s*发表时间[：:]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*",
                        "", raw
                    ).strip()
                    if cleaned:
                        author_followups.append(cleaned)

                # ★ 删除整个回复区，防止他人内容污染正文
                reply_div.decompose()

            # ── ③ 提取主正文 ─────────────────────────────────────────
            bq_text = main_bq.get_text(separator="\n", strip=True)
            bq_text = re.sub(r"^投稿经验[：:]\s*", "", bq_text).strip()

            # ── ④ 拼接作者追加内容 ───────────────────────────────────
            if author_followups:
                bq_text = bq_text + "\n--- 作者追加 ---\n" + "\n".join(author_followups)

            experience = bq_text

        # 必须有正文才算有效记录
        if not experience:
            continue

        records.append({
            "floor":      floor,
            "author":     author,
            "rating":     rating,
            "direction":  direction,
            "result":     result,
            "period":     period,
            "pub_date":   pub_date,
            "experience": experience,
            "comment_id": comment_id,   # LetPub 内部评论 ID，用于精准去重
        })

    return records


def _get_page_url(base_url: str, page: int) -> str:
    """
    构造翻页 URL。
    LetPub 后端支持 &cp=N 分页（即使前端用无限滚动展示）。
    每页约 10 条，cp=1 为第一页。
    """
    if page <= 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}cp={page}"


def get_letpub_comments(
    journal_url: str,
    cookie: str,
    target_count: int = 50,
    max_retries: int = 3,
) -> List[Dict]:
    """
    抓取 LetPub 期刊的用户投稿经验，使用真实的 JSON API 接口。

    ━━━ 工作原理 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    LetPub 评论区是 AJAX 动态加载的，requests 直接请求详情页 HTML
    拿不到评论内容。真实流程：
      ① 请求详情页 → 从 JS 里提取 AJAX 专用内部 journalid
         （详情页 URL 里的 journalid 与 AJAX 接口用的是两套 ID）
      ② 循环请求 JSON API：
         GET journalappAjax_comments_center.php
             ?action=getdetailscommentslistflow
             &journalid=<内部ID>
             &page=N
         返回：{code, count, pages, data:[{content: "<HTML片段>"}, ...]}
      ③ 解析每条 data[].content 里的 HTML，提取结构化字段

    参数
    ----
    journal_url  : 期刊详情页 URL（如 .../journalid=8411）
    cookie       : 登录后的 Cookie（需要登录才能查看完整评论）
    target_count : 目标条数（默认 50，最多抓取的上限）
    max_retries  : 单次请求最大重试次数

    返回
    ----
    List[Dict]，每条包含：
      floor / author / rating / direction /
      result / period / pub_date / experience / comment_id
    """
    # ── Step 1：从详情页 HTML 中提取 AJAX 专用的内部 journalid ────────
    # 详情页 URL 里的 journalid（如 8411）是搜索 ID，
    # 评论 AJAX 接口用的是另一套内部 ID（如 3631），
    # 它藏在详情页 JS 里：addcommentcenterAjax(3631, ...)
    session = requests.Session()
    headers = _build_headers(cookie, referer="https://www.letpub.com.cn/")

    print(f"[JournalFlow] 获取详情页，提取评论 AJAX ID：{journal_url}")
    ajax_journal_id: Optional[str] = None
    try:
        resp = session.get(journal_url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        # 从 JS 调用 addcommentcenterAjax(3631, ...) 里抓第一个参数
        m = re.search(r"addcommentcenterAjax\((\d+)\s*,", resp.text)
        if m:
            ajax_journal_id = m.group(1)
            print(f"[JournalFlow] ✓ 评论 AJAX ID = {ajax_journal_id}")
        else:
            print("[JournalFlow] ✗ 未能从详情页提取评论 ID，可能未登录或页面结构变化")
            return []
    except requests.RequestException as e:
        print(f"[JournalFlow] 详情页请求失败：{e}")
        return []

    # ── Step 2：调用真正的评论 JSON API ───────────────────────────────
    # 接口：journalappAjax_comments_center.php
    # 参数：action=getdetailscommentslistflow & journalid=XXXX & page=N
    # 每页 10 条，返回 JSON {code, count, pages, data:[{content:HTML}, ...]}
    AJAX_URL = "https://www.letpub.com.cn/journalappAjax_comments_center.php"
    all_comments: List[Dict] = []
    total_pages: Optional[int] = None

    for page_num in range(1, 9999):
        if len(all_comments) >= target_count:
            break
        if total_pages is not None and page_num > total_pages:
            break

        api_headers = _build_headers(cookie, referer=journal_url)
        params = {
            "action":    "getdetailscommentslistflow",
            "journalid": ajax_journal_id,
            "sorttype":  "undefined",
            "page":      page_num,
        }

        data = None
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[JournalFlow] 第 {page_num} 页（第 {attempt} 次请求）...")
                r = session.get(AJAX_URL, params=params,
                                headers=api_headers, timeout=15)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                print(f"[JournalFlow] 请求失败：{e}，{'重试...' if attempt < max_retries else '放弃'}")
                time.sleep(random.uniform(2, 4))

        if not data or data.get("code") != 0:
            print(f"[JournalFlow] API 返回异常：{data}")
            break

        # 首次请求时记录总页数
        if total_pages is None:
            total_pages = int(data.get("pages", 1))
            total_count = int(data.get("count", 0))
            print(f"[JournalFlow] 共 {total_count} 条评论，{total_pages} 页")

        items = data.get("data", [])
        if not items:
            print("[JournalFlow] 已到末页，停止")
            break

        page_records: List[Dict] = []
        for item in items:
            html_fragment = item.get("content", "")
            if html_fragment:
                page_records.extend(_parse_comments_from_html(html_fragment))

        print(f"[JournalFlow] 第 {page_num} 页解析到 {len(page_records)} 条")
        all_comments.extend(page_records)

        if page_num < total_pages and len(all_comments) < target_count:
            t = random.uniform(2, 4)
            print(f"[JournalFlow] 等待 {t:.1f}s...")
            time.sleep(t)

    # ── Step 3：按 comment_id 去重，截断到目标数量 ───────────────────
    seen_ids: set = set()
    unique: List[Dict] = []
    for rec in all_comments:
        key = rec.get("comment_id") or rec.get("floor", "")
        if key and key not in seen_ids:
            seen_ids.add(key)
            unique.append(rec)

    result = unique[:target_count]
    print(f"[JournalFlow] 完成，共 {len(result)} 条有效评论")
    return result


# ================================================================
# 总入口：期刊名 → 自动搜索 ID → 抓取评论（一步到位）
# ================================================================

def fetch_comments_by_name(
    journal_name: str,
    cookie: str,
    target_count: int = 50,
) -> List[Dict]:
    """
    【推荐主入口】输入期刊名称，自动完成搜索 → ID匹配 → 评论抓取。

    参数
    ----
    journal_name : 期刊名（英文全称/缩写均可）
                   示例："Nature Communications"、"AAAI"、"TPAMI"
    cookie       : 登录后的 Cookie 字符串
    target_count : 目标评论条数（默认 50）

    返回
    ----
    List[Dict]：结构化评论列表，每项包含：
      floor / author / rating / direction / result / period / pub_date / experience

    示例
    ----
    >>> records = fetch_comments_by_name("Nature Communications", MY_COOKIE)
    >>> print(records[0]["experience"])   # 打印第一条投稿经验正文
    >>> print(records[0]["period"])       # 打印投稿周期
    """
    print(f"\n{'='*60}")
    print(f"[JournalFlow] 任务开始：'{journal_name}'")
    print(f"{'='*60}")

    candidates = search_journal(journal_name, cookie=cookie)
    best = pick_best_journal(candidates, journal_name)
    if best is None:
        return []

    print(f"\n[JournalFlow] 目标期刊信息：")
    print(f"  名称 : {best['full_name']}")
    print(f"  ID   : {best['journal_id']}")
    print(f"  ISSN : {best['issn']}")
    print(f"  URL  : {best['detail_url']}\n")

    return get_letpub_comments(
        journal_url=best["detail_url"],
        cookie=cookie,
        target_count=target_count,
    )


# ================================================================
# 本地测试入口
# ================================================================
if __name__ == "__main__":

    # ── 【方式一】推荐：直接输入期刊名，全自动运行 ──────────────────
    JOURNAL_NAME = "Nature Communications"   # ← 改成你需要分析的期刊名

    records = fetch_comments_by_name(
        journal_name=JOURNAL_NAME,
        cookie=MY_COOKIE,
        target_count=50,
    )

    # ── 【方式二】已知 journalid 时，跳过搜索直接抓取 ───────────────
    # JOURNAL_ID = "8411"
    # records = get_letpub_comments(
    #     journal_url=LETPUB_DETAIL_BASE + JOURNAL_ID,
    #     cookie=MY_COOKIE,
    #     target_count=50,
    # )

    # ── 打印结构化预览（前 3 条）────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"共获取 {len(records)} 条评论，前 3 条预览：")
    print("=" * 60)
    for rec in records[:3]:
        print(f"\n  #{rec['floor']}楼  作者：{rec['author']}")
        print(f"  研究方向：{rec['direction']}  |  投稿结果：{rec['result']}")
        print(f"  投稿周期：{rec['period']}  |  发表时间：{rec['pub_date']}")
        exp_preview = rec["experience"][:200].replace("\n", " ")
        print(f"  投稿经验：{exp_preview}{'...' if len(rec['experience']) > 200 else ''}")
        print("  " + "─" * 55)

    # ── 保存到本地 JSON ─────────────────────────────────────────────
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", JOURNAL_NAME)
    output_path = f"letpub_{safe_name}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\n[JournalFlow] 结果已保存至：{output_path}")
    print(f"[JournalFlow] JSON 字段：floor / author / rating / direction / result / period / pub_date / experience")
