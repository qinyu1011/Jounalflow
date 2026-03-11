"""
analyzer.py  —  基于 T_ 时间节点的精细化统计分析
"""
from collections import Counter, defaultdict
from datetime import date
from typing import List, Dict, Optional
import statistics

from llm_extractor import RESULT_LABELS

# ── 派生周期定义 ─────────────────────────────────────────────────
# 每个 phase: (key, label, from_field, to_field, description)
PHASES = [
    ("editor_speed_1",   "① 初审编辑处理速度",
     "T_Submit",          "T_WithEditor_1",
     "投稿 → 首次进编辑（编辑多久拿到稿件）"),

    ("submit_to_review_1","② 投稿到首次送审",
     "T_Submit",          "T_UnderReview_1",
     "投稿 → 首次送审（总等待时间）"),

    ("first_review_cycle","③ 一审周期",
     "T_UnderReview_1",   "T_FirstDecision_date",
     "首次送审 → 一审结果（审稿人耗时）"),

    ("revision_turnaround","④ 作者修改耗时",
     "T_FirstDecision_date","T_Revision_Submit",
     "一审结果 → 作者提交修改稿"),

    ("editor_speed_2",   "⑤ 修回后编辑处理速度",
     "T_Revision_Submit", "T_UnderReview_2",
     "提交修改稿 → 二审送审（编辑压稿时间）"),

    ("second_review_cycle","⑥ 二审周期",
     "T_UnderReview_2",   "T_SecondDecision_date",
     "二审送审 → 二审结果"),

    ("revision_to_accept","⑦ 末次修改到录用",
     "T_Revision_Submit", "T_Accept",
     "最后一次提交修改稿 → 录用"),

    ("total_cycle",      "⑧ 整体接收周期（总时间）",
     "T_Submit",          "T_Accept",
     "投稿 → 最终录用（全程）"),
]


def _diff(c: dict, f1: str, f2: str) -> Optional[float]:
    """计算两个 T_ 字段之间的天数差，任一为 None 则返回 None"""
    d1, d2 = c.get(f1), c.get(f2)
    if not d1 or not d2:
        return None
    try:
        a = date.fromisoformat(str(d1)[:10])
        b = date.fromisoformat(str(d2)[:10])
        diff = (b - a).days
        return diff if 0 < diff < 800 else None   # 过滤异常值
    except Exception:
        return None


def _phase_stats(vals: List[float]) -> Optional[Dict]:
    if not vals:
        return None
    return {
        "count":  len(vals),
        "mean":   round(statistics.mean(vals), 1),
        "median": round(statistics.median(vals), 1),
        "min":    int(min(vals)),
        "max":    int(max(vals)),
        "stdev":  round(statistics.stdev(vals), 1) if len(vals) > 1 else 0,
    }


def analyze(comments: List[Dict]) -> Dict:
    total = len(comments)
    if total == 0:
        return _empty()

    # ── 1. 投稿结果分布 ─────────────────────────────────────────
    result_counter = Counter(c.get("final_result","unknown") for c in comments)
    result_dist = [
        {"key":k, "label":RESULT_LABELS.get(k,k),
         "count":v, "pct":round(v/total*100,1)}
        for k, v in result_counter.most_common()
    ]

    # ── 2. 各派生周期统计 ────────────────────────────────────────
    phase_data: Dict[str, List[float]] = defaultdict(list)
    for c in comments:
        for key, label, f1, f2, desc in PHASES:
            d = _diff(c, f1, f2)
            if d is not None:
                phase_data[key].append(d)

    phase_stats = []
    for key, label, f1, f2, desc in PHASES:
        vals = phase_data[key]
        s = _phase_stats(vals)
        if s:
            phase_stats.append({
                "key":   key,
                "label": label,
                "desc":  desc,
                "from":  f1,
                "to":    f2,
                **s,
            })

    # ── 3. 总周期分布直方图（用于图表） ──────────────────────────
    total_days = [d for d in phase_data["total_cycle"] if d]
    cycle_histogram = _histogram(total_days, bins=10)

    # ── 4. 一审结果类型分布 ──────────────────────────────────────
    first_decision_dist = Counter(
        c.get("T_FirstDecision_type","unknown")
        for c in comments
        if c.get("T_FirstDecision_date")
    )

    # ── 5. 修改轮数分布 ──────────────────────────────────────────
    revision_dist = Counter(
        int(c.get("revision_count") or 0)
        for c in comments
    )

    # ── 6. 月度投稿趋势 ──────────────────────────────────────────
    month_counter: Dict[str,int] = defaultdict(int)
    for c in comments:
        d = c.get("T_Submit")
        if d and len(str(d)) >= 7:
            month_counter[str(d)[:7]] += 1
    submission_trend = [
        {"month":k,"count":v}
        for k,v in sorted(month_counter.items())
    ]

    # ── 7. 关键 KPI ──────────────────────────────────────────────
    accepted = result_counter.get("accepted", 0)
    rejected = result_counter.get("rejected", 0)
    decided  = accepted + rejected
    accept_rate = round(accepted/decided*100, 1) if decided else None

    total_s  = _phase_stats(phase_data["total_cycle"])
    first_rv = _phase_stats(phase_data["first_review_cycle"])

    return {
        "total":              total,
        "accept_rate":        accept_rate,
        "decided_count":      decided,
        "result_dist":        result_dist,
        "phase_stats":        phase_stats,
        "cycle_histogram":    cycle_histogram,
        "submission_trend":   submission_trend,
        "first_decision_dist": dict(first_decision_dist),
        "revision_dist":      dict(revision_dist),
        "kpi": {
            "total_cycle_mean":   total_s["mean"]   if total_s else None,
            "total_cycle_median": total_s["median"] if total_s else None,
            "total_cycle_min":    total_s["min"]    if total_s else None,
            "total_cycle_max":    total_s["max"]    if total_s else None,
            "first_review_mean":  first_rv["mean"]  if first_rv else None,
            "accept_rate":        accept_rate,
        },
    }


def _histogram(values, bins=10):
    if not values: return []
    lo, hi = min(values), max(values)
    if lo == hi: return [{"label": str(int(lo))+"天", "count": len(values)}]
    width = (hi - lo) / bins
    buckets = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        buckets[idx] += 1
    return [
        {"label": f"{int(lo+i*width)}-{int(lo+(i+1)*width)}天", "count": cnt}
        for i, cnt in enumerate(buckets)
    ]


def _empty():
    return {
        "total":0,"accept_rate":None,"decided_count":0,
        "result_dist":[],"phase_stats":[],"cycle_histogram":[],
        "submission_trend":[],"first_decision_dist":{},
        "revision_dist":{},"kpi":{},
    }
