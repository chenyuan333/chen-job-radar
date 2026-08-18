"""
岗位雷达小程序 - Flask 主应用
启动：python app.py
访问：http://127.0.0.1:5173
"""
import os
import json
from datetime import datetime

from flask import Flask, request, jsonify, render_template, send_from_directory, Response

import database
import parser
import crawler


app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_AS_ASCII"] = False


def cleanup_on_startup():
    """
    启动时清理：
    1. 重新识别所有 active 岗位的城市；
    2. 把明确非东莞/广州或地点不明的岗位标为 expired；
    3. 校正剩余岗位的城市字段。
    """
    try:
        database.init_db()
        jobs = database.list_jobs(filters={"status": "active"})
        for j in jobs:
            # 判断真实地点时只看 title/hospital/description，
            # 避免 source/query 关键词里的"东莞/广州"污染判断
            text = " ".join([
                j.get("title", ""),
                j.get("hospital", ""),
                j.get("description", ""),
            ])
            if parser.has_wrong_region(text):
                database.update_job(j["id"], {"status": "expired"})
                continue
            chosen = parser.pick_city(text)
            if not chosen:
                database.update_job(j["id"], {"status": "expired"})
                continue
            if j.get("city") != chosen:
                database.update_job(j["id"], {"city": chosen})
    except Exception:
        # 启动清理失败不应阻断服务
        pass


@app.before_request
def ensure_db():
    if not os.path.exists(database.DB_PATH):
        database.init_db()


# 应用启动时立即执行一次清理（对 gunicorn worker 也生效）
cleanup_on_startup()


# ============== 页面 ==============

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon.ico", mimetype="image/x-icon") if os.path.exists("static/favicon.ico") else ("", 204)


# ============== 岗位 API ==============

@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    filters = {
        "category": request.args.get("category", "").strip() or None,
        "city": request.args.get("city", "").strip() or None,
        "user_status": request.args.get("user_status", "").strip() or None,
        "status": request.args.get("status", "").strip() or None,
        "has_bianzhi": request.args.get("has_bianzhi") == "1",
        "q": request.args.get("q", "").strip() or None,
        "hide_expired": request.args.get("hide_expired") == "1",
        "only_fresh": request.args.get("only_fresh") == "1",
    }
    jobs = database.list_jobs(filters)
    return jsonify({"ok": True, "jobs": jobs, "count": len(jobs)})


@app.route("/api/jobs", methods=["POST"])
def api_jobs_add():
    data = request.get_json() or {}
    result = database.add_job(data)
    return jsonify({"ok": result[0] == "inserted", "status": result[0], "id": result[1], "msg": result[0] if result[0] != "inserted" else "ok"})


@app.route("/api/jobs/<int:job_id>", methods=["PATCH"])
def api_jobs_patch(job_id):
    data = request.get_json() or {}
    ok = database.update_job(job_id, data)
    return jsonify({"ok": ok})


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def api_jobs_delete(job_id):
    database.delete_job(job_id)
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>", methods=["GET"])
def api_jobs_get(job_id):
    job = database.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "msg": "not found"}), 404
    return jsonify({"ok": True, "job": job})


# ============== 抓取 API ==============

@app.route("/api/crawl/paste", methods=["POST"])
def api_crawl_paste():
    """用户粘贴搜索结果文本 → 解析入库"""
    data = request.get_json() or {}
    text = data.get("text", "")
    source = data.get("source", "手动粘贴")
    if not text.strip():
        return jsonify({"ok": False, "msg": "粘贴内容为空"}), 400
    result = crawler.crawl_from_paste(text, source_label=source)
    return jsonify({"ok": True, **result})


@app.route("/api/crawl/fetch-url", methods=["POST"])
def api_crawl_fetch_url():
    """根据 URL 抓页面，自动识别岗位信息（带回填表单）"""
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "msg": "url 为空"}), 400
    info = crawler.fetch_url_summary(url)
    if not info:
        return jsonify({"ok": False, "msg": "抓取失败"}), 500
    if "error" in info:
        return jsonify({"ok": False, "msg": info["error"]}), 500
    return jsonify({"ok": True, "info": info})


@app.route("/api/crawl/sweep", methods=["POST"])
def api_crawl_sweep():
    """扫描并标记过期岗位"""
    updated = crawler.sweep_expired()
    return jsonify({"ok": True, "expired_marked": updated})


@app.route("/api/crawl/tavily", methods=["POST"])
def api_crawl_tavily():
    """
    Tavily 自动联网搜索（需 TAVILY_API_KEY 环境变量）
    请求体：可选 {queries: [[query, city], ...], days: 60, max_per_query: 8}
    """
    data = request.get_json(silent=True) or {}
    queries = None
    if data.get("queries"):
        queries = [tuple(q) for q in data["queries"]]
    days = int(data.get("days", 60))
    max_per_query = int(data.get("max_per_query", 8))
    result = crawler.search_tavily_for_jobs(queries=queries, days=days, max_per_query=max_per_query)
    if "error" in result:
        return jsonify({"ok": False, "msg": result["error"]}), 400
    database.set_setting("last_crawl_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return jsonify({"ok": True, **result})


@app.route("/api/crawl/deadlinks", methods=["POST"])
def api_crawl_deadlinks():
    """链接活性巡检（异步跑小批次，避免阻塞）"""
    data = request.get_json(silent=True) or {}
    n = int(data.get("sample_size", 80))
    result = crawler.sweep_dead_links(sample_size=n)
    return jsonify({"ok": True, **result})


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "ok": True,
        "service": "陈医生岗位雷达",
        "version": "1.0",
        "tavily_configured": bool(os.environ.get("TAVILY_API_KEY")),
        "scheduler_enabled": os.environ.get("ENABLE_SCHEDULER") == "1",
        "time": datetime.now().isoformat(timespec="seconds"),
    })


# ============== 设置 + 元信息 ==============

@app.route("/api/stats", methods=["GET"])
def api_stats():
    s = database.stats()
    s["last_crawl_at"] = database.get_setting("last_crawl_at") or "从未抓取"
    s["categories"] = json.loads(database.get_setting("default_categories") or "[]")
    return jsonify(s)


@app.route("/api/crawl-logs", methods=["GET"])
def api_crawl_logs():
    logs = database.list_crawl_logs(limit=20)
    return jsonify({"ok": True, "logs": logs})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        keys = ["default_keywords", "default_city", "default_categories", "last_crawl_at"]
        return jsonify({k: database.get_setting(k) for k in keys})
    data = request.get_json() or {}
    for k, v in data.items():
        database.set_setting(k, str(v))
    return jsonify({"ok": True})


# ============== 导出 ==============

@app.route("/api/export", methods=["GET"])
def api_export():
    fmt = request.args.get("format", "csv").lower()
    jobs = database.list_jobs({"city": ""})  # 空 city 会触发默认东莞/广州白名单过滤
    if fmt == "json":
        return Response(
            json.dumps({"jobs": jobs, "exported_at": datetime.now().isoformat()}, ensure_ascii=False, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="jobs.json"'},
        )
    # CSV
    import csv, io
    output = io.StringIO()
    if jobs:
        fieldnames = [
            "id", "title", "hospital", "city", "category", "salary",
            "url", "publish_date", "deadline", "has_bianzhi", "reliability",
            "status", "user_status", "added_at", "notes",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for j in jobs:
            j2 = dict(j)
            j2["has_bianzhi"] = "是" if j2.get("has_bianzhi") else ""
            writer.writerow(j2)
    response = Response(
        "\ufeff" + output.getvalue(),  # BOM for Excel 兼容
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="jobs.csv"'},
    )
    return response


if __name__ == "__main__":
    database.init_db()
    crawler.sweep_expired()  # 启动时顺带扫一次
    crawler.start_scheduler_if_enabled()  # 云端环境变量开启时启动每日自动搜索
    port = int(os.environ.get("PORT", "5173"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"""
╔════════════════════════════════════════════════════════╗
║      🍊 陈医生岗位雷达小程序 - 启动成功                ║
╠════════════════════════════════════════════════════════╣
║  访问地址：http://{host}:{port:<39} ║
║  数据库：{database.DB_PATH:<40} ║
║  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<40} ║
╚════════════════════════════════════════════════════════╝
""")
    app.run(host=host, port=port, debug=False, use_reloader=False)
