# -*- coding: utf-8 -*-
"""检测 jobs.json 中所有岗位链接的有效性"""
import json, re, ssl, urllib.request, urllib.error, concurrent.futures
from datetime import datetime

PY = "C:/Users/陈圆圆/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

def check(item):
    url = item.get("url", "")
    title = item.get("title", "")
    deadline = item.get("deadline") or ""
    result = {"title": title, "url": url, "deadline": deadline, "status": "NO_URL"}
    if not url or not url.startswith("http"):
        return result
    try:
        req = urllib.request.Request(url, headers=HEADERS, method="GET")
        with urllib.request.urlopen(req, timeout=20, context=CTX) as resp:
            code = resp.status
            body = resp.read(60000).decode("utf-8", errors="ignore")
            result["status"] = str(code)
            # 内容层面判断：404文案 / 已结束 / 已下线
            dead_kw = ["页面不存在", "404", "Not Found", "内容不存在", "已删除", "链接已失效",
                       "职位已关闭", "已停止招聘", "招聘已结束", "公告不存在", "访问出错"]
            low = body.lower()
            if any(k.lower() in low for k in dead_kw):
                result["status"] += "+DEAD_CONTENT"
            result["body_len"] = len(body)
    except urllib.error.HTTPError as e:
        result["status"] = "HTTP_%d" % e.code
    except Exception as e:
        result["status"] = "ERR:%s" % type(e).__name__
    return result

def main():
    data = json.load(open("pwa/jobs.json", encoding="utf-8"))
    jobs = data.get("jobs", [])
    today = datetime.now()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check, jobs))
    print("today:", today.strftime("%Y-%m-%d"))
    print("=" * 100)
    for r in results:
        expired = ""
        if r["deadline"]:
            try:
                d = datetime.strptime(r["deadline"][:10], "%Y-%m-%d")
                if d < today:
                    expired = " | <<<DEADLINE_PASSED"
            except ValueError:
                pass
        print("[%s]%s | %s | %s" % (r["status"], expired, r["title"][:35], r["url"][:75]))

if __name__ == "__main__":
    main()
