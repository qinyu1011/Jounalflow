"""
app.py  —  Flask 后端 + SSE
"""
import json, queue, threading, uuid
from datetime import datetime
from flask import Flask, Response, jsonify, render_template, request
import config

app = Flask(__name__)
_tasks: dict = {}
_lock = threading.Lock()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def start_analyze():
    data = request.get_json(force=True)
    journal_name  = (data.get("journal_name") or "").strip()
    comment_count = min(int(data.get("comment_count") or config.DEFAULT_COMMENTS),
                        config.MAX_COMMENTS)
    if not journal_name:
        return jsonify({"error": "期刊名称不能为空"}), 400

    task_id = str(uuid.uuid4())
    q = queue.Queue()
    with _lock:
        _tasks[task_id] = {
            "status": "running", "queue": q,
            "result": None, "error": None,
            "created": datetime.now().isoformat(),
        }

    threading.Thread(
        target=_run, args=(task_id, journal_name, comment_count), daemon=True
    ).start()
    return jsonify({"task_id": task_id})


@app.route("/api/stream/<task_id>")
def stream(task_id):
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        return Response('data: {"error":"任务不存在"}\n\n',
                        mimetype="text/event-stream")
    def generate():
        q = task["queue"]
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") in ("done","error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"heartbeat"}\n\n'
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.route("/api/result/<task_id>")
def get_result(task_id):
    with _lock:
        task = _tasks.get(task_id)
    if not task: return jsonify({"error":"任务不存在"}), 404
    if task["status"] != "done":
        return jsonify({"error":"任务尚未完成","status":task["status"]}), 202
    return jsonify(task["result"])


def _push(task_id, msg):
    with _lock:
        task = _tasks.get(task_id)
    if task:
        task["queue"].put(msg)


def _run(task_id, journal_name, count):
    try:
        # 使用 LangChain Agent（安装 langchain 后自动启用）
        try:
            from agent import JournalFlowAgent
            agent = JournalFlowAgent()
            for event in agent.run_stream(journal_name, count=count):
                _push(task_id, event)
                if event.get("type") == "done":
                    with _lock:
                        _tasks[task_id]["status"] = "done"
                        _tasks[task_id]["result"] = event["result"]
                elif event.get("type") == "error":
                    with _lock:
                        _tasks[task_id]["status"] = "error"
                        _tasks[task_id]["error"]  = event.get("text","")
        except ImportError:
            # langchain 未安装时降级为直接调用
            _run_direct(task_id, journal_name, count)
    except Exception as e:
        import traceback
        _push(task_id, {"type":"error","text":f"❌ 任务异常：{e}",
                        "detail": traceback.format_exc()})
        with _lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"]  = str(e)


def _run_direct(task_id, journal_name, count):
    """langchain 未安装时的降级执行路径"""
    from letpub_scraper import fetch_comments_by_name
    from llm_extractor import extract_batch, RESULT_LABELS
    from analyzer import analyze, _diff

    _push(task_id, {"type":"step","step":1,
                    "text":f"🔍 正在搜索并抓取「{journal_name}」评论..."})
    comments = fetch_comments_by_name(journal_name, config.LETPUB_COOKIE, count)
    if not comments:
        _push(task_id, {"type":"error","text":"❌ 未找到期刊或无评论"})
        with _lock: _tasks[task_id]["status"] = "error"
        return
    _push(task_id, {"type":"step","step":1,
                    "text":f"✅ 抓取完成，共 {len(comments)} 条"})

    _push(task_id, {"type":"step","step":2,
                    "text":f"🤖 LLM 提取时间节点（{len(comments)} 条）..."})
    total = len(comments)
    def on_prog(cur, ttl, res):
        fr = res.get("final_result","?")
        label = RESULT_LABELS.get(fr, fr)
        d = _diff(res, "T_Submit", "T_Accept")
        days_str = f"，{d}天" if d else ""
        _push(task_id, {
            "type":"progress","current":cur,"total":ttl,
            "pct":int(cur/ttl*100),
            "text":f"  [{cur}/{ttl}] #{res.get('floor','?')}楼 → {label}{days_str} "
                   f"{'✓' if not res.get('llm_error') else '⚠'}",
        })
    extracted = extract_batch(comments, progress_callback=on_prog, delay=0.2)
    _push(task_id, {"type":"step","step":2,"text":"✅ LLM 提取完成"})

    _push(task_id, {"type":"step","step":3,"text":"📊 统计分析..."})
    stats = analyze(extracted)
    _push(task_id, {"type":"step","step":3,"text":"✅ 分析完成"})

    comment_list = [{k: c.get(k) for k in [
        "floor","author","rating","direction","result","period",
        "pub_date","experience","final_result","revision_count",
        "llm_notes","llm_error",
        "T_Submit","T_WithEditor_1","T_UnderReview_1",
        "T_FirstDecision_date","T_FirstDecision_type",
        "T_Revision_Submit","T_WithEditor_2","T_UnderReview_2",
        "T_SecondDecision_date","T_SecondDecision_type","T_Accept",
    ]} for c in extracted]

    final = {
        "journal_name": journal_name,
        "scraped_at":   datetime.now().isoformat(),
        "stats":        stats,
        "comments":     comment_list,
    }
    with _lock:
        _tasks[task_id]["status"] = "done"
        _tasks[task_id]["result"] = final
    _push(task_id, {"type":"done","text":"✅ 全部完成！","result":final})


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
