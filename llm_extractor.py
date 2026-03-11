"""
llm_extractor.py  —  细粒度 T_ 时间节点提取
"""
import json, time
from openai import OpenAI
import config

_client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

RESULT_LABELS = {
    "accepted":"录用","rejected":"拒稿","major_revision":"大修",
    "minor_revision":"小修","under_review":"在审中",
    "withdrawn":"撤稿","unknown":"未知",
}
DECISION_LABELS = {
    "major_revision":"大修","minor_revision":"小修",
    "rejected":"拒稿","accepted":"直接录用","unknown":"未知",
}

SYSTEM_PROMPT = r"""你是学术投稿数据提取专家。从 LetPub 投稿经验（中英混合口语文本）中提取精确时间节点。

【投稿流程模型】
初次投稿→进编辑→送审→一审决定(大修/小修/拒稿/直录)
→[若修改]提交修改稿→进编辑→送审→二审决定→...→最终录用/拒稿

【常见缩写】
STJ/stj/submitted→投稿  WE/we/with editor→进编辑
UR/ur/under review→送审  RRC→审稿人完成
MR/major/大修→大修  minor/小修→小修
Accept/录用→录用  Reject/拒稿→拒稿  R1→第一次修改

【严格只输出JSON，不含其他文字】
{
  "T_Submit":          "YYYY-MM-DD or null",
  "T_WithEditor_1":    "YYYY-MM-DD or null",
  "T_UnderReview_1":   "YYYY-MM-DD or null",
  "T_FirstDecision":   {"date":"YYYY-MM-DD or null","type":"major_revision|minor_revision|rejected|accepted|unknown"},
  "T_Revision_Submit": "YYYY-MM-DD or null",
  "T_WithEditor_2":    "YYYY-MM-DD or null",
  "T_UnderReview_2":   "YYYY-MM-DD or null",
  "T_SecondDecision":  {"date":"YYYY-MM-DD or null","type":"major_revision|minor_revision|rejected|accepted|unknown"},
  "T_Accept":          "YYYY-MM-DD or null",
  "final_result":      "accepted|rejected|major_revision|minor_revision|under_review|withdrawn|unknown",
  "revision_count":    0,
  "notes":             "简短备注"
}

【日期规则】
- "25.9.13"→"2025-09-13"  "26.1.8"→"2026-01-08"  仅月份→YYYY-MM-01
- T_Accept优先用原文明确accept日期，其次参考"网站标注发表时间"
- 无法确定→null
【revision_count】= 作者实际提交修改稿次数（0=未修改/仍在审）"""

def extract_one(comment: dict, max_retries: int = 3) -> dict:
    ctx = []
    if comment.get("pub_date"):  ctx.append(f"网站标注发表时间：{comment['pub_date']}")
    if comment.get("result"):    ctx.append(f"网站标注结果：{comment['result']}")
    if comment.get("period"):    ctx.append(f"网站标注周期：{comment['period']}")
    context = "\n".join(ctx)
    exp = comment.get("experience", "（无内容）")

    result = comment.copy()
    result["llm_error"] = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = _client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role":"system","content":SYSTEM_PROMPT},
                    {"role":"user","content":f"{context}\n\n投稿经验原文：\n{exp}"},
                ],
                temperature=0.05, max_tokens=600,
                response_format={"type":"json_object"},
            )
            parsed = json.loads(resp.choices[0].message.content.strip())
            result["T_Submit"]            = parsed.get("T_Submit")
            result["T_WithEditor_1"]      = parsed.get("T_WithEditor_1")
            result["T_UnderReview_1"]     = parsed.get("T_UnderReview_1")
            fd = parsed.get("T_FirstDecision") or {}
            result["T_FirstDecision_date"] = fd.get("date")
            result["T_FirstDecision_type"] = fd.get("type","unknown")
            result["T_Revision_Submit"]   = parsed.get("T_Revision_Submit")
            result["T_WithEditor_2"]      = parsed.get("T_WithEditor_2")
            result["T_UnderReview_2"]     = parsed.get("T_UnderReview_2")
            sd = parsed.get("T_SecondDecision") or {}
            result["T_SecondDecision_date"] = sd.get("date")
            result["T_SecondDecision_type"] = sd.get("type","unknown")
            result["T_Accept"]            = parsed.get("T_Accept")
            result["final_result"]        = parsed.get("final_result","unknown")
            result["revision_count"]      = parsed.get("revision_count",0)
            result["llm_notes"]           = parsed.get("notes","")
            return result
        except json.JSONDecodeError as e:
            result["llm_error"] = f"JSON解析失败：{e}"
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                time.sleep(2**attempt)
            else:
                result["llm_error"] = err; break

    for key in ["T_Submit","T_WithEditor_1","T_UnderReview_1","T_FirstDecision_date",
                "T_Revision_Submit","T_WithEditor_2","T_UnderReview_2",
                "T_SecondDecision_date","T_Accept"]:
        result.setdefault(key, None)
    for k,v in [("T_FirstDecision_type","unknown"),("T_SecondDecision_type","unknown"),
                ("final_result","unknown"),("revision_count",0),("llm_notes","")]:
        result.setdefault(k, v)
    return result

def extract_batch(comments, progress_callback=None, delay=0.3):
    results = []
    total = len(comments)
    for i, c in enumerate(comments, 1):
        res = extract_one(c)
        results.append(res)
        if progress_callback: progress_callback(i, total, res)
        if i < total: time.sleep(delay)
    return results
