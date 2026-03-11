"""
agent.py  —  JournalFlow LangChain Agent
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
将爬虫/LLM提取/统计分析封装为 LangChain Tools，
由 Agent 自主编排完成"期刊名 → 分析看板数据"的完整工作流。

使用方式
--------
from agent import JournalFlowAgent
agent = JournalFlowAgent()
for event in agent.run_stream("Nature Communications", count=50):
    print(event)   # {"type":"step"/"progress"/"done"/"error", ...}

LangChain 组件
--------------
- Tool: scrape_journal_comments
- Tool: extract_timelines
- Tool: compute_statistics
- AgentExecutor (ReAct 风格，OpenAI Function Calling)
"""

import json
from typing import Generator, Optional
from langchain.tools import tool
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import SystemMessage

import config
from letpub_scraper import fetch_comments_by_name
from llm_extractor import extract_batch, RESULT_LABELS
from analyzer import analyze

# ── 共享状态（Agent 工具间传递中间结果） ──────────────────────────
class _AgentState:
    comments: list = []
    extracted: list = []
    stats: dict = {}
    journal_name: str = ""

_state = _AgentState()


# ================================================================
# Tool 定义
# ================================================================

@tool
def scrape_journal_comments(journal_name: str, count: int = 50) -> str:
    """
    从 LetPub 抓取期刊投稿经验评论。
    输入：期刊名称（英文全称或缩写）和目标条数。
    返回：抓取到的评论数量摘要。
    """
    _state.journal_name = journal_name
    comments = fetch_comments_by_name(
        journal_name=journal_name,
        cookie=config.LETPUB_COOKIE,
        target_count=count,
    )
    _state.comments = comments
    if not comments:
        return f"未找到期刊「{journal_name}」的评论，请检查期刊名称或 Cookie。"
    sample = comments[0]
    return (
        f"成功抓取 {len(comments)} 条评论。"
        f"示例：#{sample.get('floor')}楼，{sample.get('author')}，"
        f"结果：{sample.get('result')}，周期：{sample.get('period')}"
    )


@tool
def extract_timelines(batch_size: int = 0) -> str:
    """
    对已抓取的评论调用 LLM 提取精细化时间节点（T_Submit/T_WithEditor_1/...）。
    应在 scrape_journal_comments 之后调用。
    返回：提取完成的条数及成功率。
    """
    if not _state.comments:
        return "错误：请先调用 scrape_journal_comments 抓取评论。"

    total = len(_state.comments)
    extracted = extract_batch(_state.comments, delay=0.2)
    _state.extracted = extracted

    success = sum(1 for c in extracted if not c.get("llm_error"))
    failed  = total - success
    accepted = sum(1 for c in extracted if c.get("final_result") == "accepted")

    return (
        f"LLM 提取完成：{total} 条，成功 {success}，失败 {failed}。"
        f"其中识别为录用：{accepted} 条，"
        f"录用率（初步）：{round(accepted/total*100,1)}%"
    )


@tool
def compute_statistics(dummy: str = "") -> str:
    """
    对已提取的时间节点数据进行统计分析，生成各审稿阶段的耗时统计。
    应在 extract_timelines 之后调用。
    返回：关键统计指标摘要。
    """
    if not _state.extracted:
        return "错误：请先调用 extract_timelines。"

    stats = analyze(_state.extracted)
    _state.stats = stats
    kpi = stats.get("kpi", {})

    lines = [f"统计完成，共 {stats['total']} 条："]
    if kpi.get("accept_rate") is not None:
        lines.append(f"  录用率：{kpi['accept_rate']}%（基于{stats['decided_count']}条已决稿）")
    if kpi.get("total_cycle_mean"):
        lines.append(
            f"  整体接收周期：均值 {kpi['total_cycle_mean']} 天，"
            f"中位数 {kpi['total_cycle_median']} 天，"
            f"范围 {kpi['total_cycle_min']}–{kpi['total_cycle_max']} 天"
        )
    if kpi.get("first_review_mean"):
        lines.append(f"  一审周期均值：{kpi['first_review_mean']} 天")
    for phase in stats.get("phase_stats", [])[:4]:
        lines.append(
            f"  {phase['label']}：均值 {phase['mean']} 天"
            f"（n={phase['count']}，范围 {phase['min']}–{phase['max']} 天）"
        )
    return "\n".join(lines)


# ================================================================
# Agent 构建
# ================================================================

TOOLS = [scrape_journal_comments, extract_timelines, compute_statistics]

SYSTEM_PROMPT = """你是 JournalFlow 期刊投稿分析助手。
当用户提供期刊名称和评论数量时，你需要按顺序：
1. 调用 scrape_journal_comments 抓取评论
2. 调用 extract_timelines 用 LLM 提取时间节点
3. 调用 compute_statistics 进行统计分析
4. 用中文总结分析结果，包含关键统计数据

注意：
- 严格按照 1→2→3 的顺序调用工具
- 如果任何一步返回错误，停止并告知用户
- 最终总结要简洁专业，突出关键数据"""

def build_agent() -> AgentExecutor:
    llm = ChatOpenAI(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
        temperature=0,
    )
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=SYSTEM_PROMPT),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    agent = create_openai_functions_agent(llm, TOOLS, prompt)
    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=False,
        handle_parsing_errors=True,
        max_iterations=6,
    )


# ================================================================
# 流式执行接口（供 app.py SSE 使用）
# ================================================================

class JournalFlowAgent:
    """
    对外暴露的 Agent 接口。
    run_stream() 是生成器，逐步 yield 进度事件（dict）。
    """

    def __init__(self):
        self._executor = build_agent()

    def run_stream(
        self,
        journal_name: str,
        count: int = 50,
    ) -> Generator[dict, None, None]:
        """
        运行完整分析流程，yield 进度事件。

        每个事件格式：
          {"type": "step",     "step": N, "text": "..."}
          {"type": "progress", "current": N, "total": M, "pct": P, "text": "..."}
          {"type": "done",     "text": "...", "result": {...}}
          {"type": "error",    "text": "..."}
        """
        # 重置状态
        _state.comments  = []
        _state.extracted = []
        _state.stats     = {}
        _state.journal_name = journal_name

        yield {"type": "step", "step": 1,
               "text": f"🤖 Agent 启动：分析期刊「{journal_name}」（目标 {count} 条评论）"}

        # ── 步骤 1：抓取 ──────────────────────────────────────────
        yield {"type": "step", "step": 1,
               "text": f"🔍 正在搜索并抓取 LetPub 评论..."}
        try:
            _state.comments = fetch_comments_by_name(
                journal_name=journal_name,
                cookie=config.LETPUB_COOKIE,
                target_count=count,
            )
        except Exception as e:
            yield {"type": "error", "text": f"❌ 抓取失败：{e}"}
            return

        if not _state.comments:
            yield {"type": "error",
                   "text": "❌ 未找到期刊或无评论，请检查期刊名称和 Cookie"}
            return

        yield {"type": "step", "step": 1,
               "text": f"✅ 抓取完成，共 {len(_state.comments)} 条评论"}

        # ── 步骤 2：LLM 提取（带逐条进度） ───────────────────────
        yield {"type": "step", "step": 2,
               "text": f"🤖 LLM 提取时间节点（共 {len(_state.comments)} 条）..."}

        total = len(_state.comments)
        extracted = []

        def on_progress(current, ttl, res):
            pct = int(current / ttl * 100)
            status = "✓" if not res.get("llm_error") else "⚠"
            fr = res.get("final_result","?")
            label = RESULT_LABELS.get(fr, fr)
            days_str = ""
            if res.get("T_Submit") and res.get("T_Accept"):
                from analyzer import _diff
                d = _diff(res, "T_Submit", "T_Accept")
                if d:
                    days_str = f"，{d}天"
            # 把进度事件放到队列（这里用列表暂存，app.py 会轮询）
            extracted.append({
                "type":    "progress",
                "current": current,
                "total":   ttl,
                "pct":     pct,
                "text":    f"  [{current}/{ttl}] #{res.get('floor','?')}楼 "
                           f"→ {label}{days_str} {status}",
            })

        from llm_extractor import extract_batch as _eb
        _state.extracted = _eb(
            _state.comments,
            progress_callback=on_progress,
            delay=0.2,
        )

        # 把进度事件 yield 出去
        for ev in extracted:
            yield ev

        yield {"type": "step", "step": 2, "text": "✅ LLM 提取完成"}

        # ── 步骤 3：统计分析 ─────────────────────────────────────
        yield {"type": "step", "step": 3, "text": "📊 计算各阶段统计指标..."}
        _state.stats = analyze(_state.extracted)
        yield {"type": "step", "step": 3, "text": "✅ 统计分析完成"}

        # ── 组装最终结果 ─────────────────────────────────────────
        from datetime import datetime
        comment_list = [
            {k: c.get(k) for k in [
                "floor","author","rating","direction","result","period",
                "pub_date","experience","final_result","revision_count",
                "llm_notes","llm_error",
                "T_Submit","T_WithEditor_1","T_UnderReview_1",
                "T_FirstDecision_date","T_FirstDecision_type",
                "T_Revision_Submit","T_WithEditor_2","T_UnderReview_2",
                "T_SecondDecision_date","T_SecondDecision_type","T_Accept",
            ]}
            for c in _state.extracted
        ]

        final = {
            "journal_name": journal_name,
            "scraped_at":   datetime.now().isoformat(),
            "stats":        _state.stats,
            "comments":     comment_list,
        }

        yield {"type": "done", "text": "✅ 全部完成！", "result": final}
