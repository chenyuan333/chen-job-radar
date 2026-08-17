"""
抓取任务 - 岗位雷达小程序
本版实现：
1. 手动粘贴搜索结果文本 → 自动解析入库（最实用，避免反爬）
2. URL 单条抓取 → 解析标题/截止日期/类别 → 入库（用户输入链接时自动预填）
3. Tavily 自动搜索：按 6 类岗位 × 东莞/广州 关键词组合，拉取最新岗位结果
4. 周期性 sweep：扫描数据库，把已过期岗位标 expired，避免展示过期岗位
5. 链接活性巡检：定时检查所有 active 岗位的 URL，发现 404/410 自动标 expired
6. 所有抓取都自动过滤已过期岗位，并写入 crawl_logs
"""
import os
import re
import json
import time
import threading
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

import database
import parser


# 默认搜索关键词组合（6 类岗位 × 东莞/广州）
# 陈医生 2026-08-17 明确：只要东莞和广州，其他城市不要
DEFAULT_SEARCH_QUERIES = [
    # 体检科 / 健康管理中心
    ("体检科医师 招聘 2026", "东莞"),
    ("健康管理中心医师 招聘 2026", "东莞"),
    ("体检科医师 招聘 2026", "广州"),
    ("健康管理科医师 招聘 2026 编制", "广州"),
    # 心电图
    ("心电图医师 招聘 2026", "东莞"),
    ("心电图室医生 招聘 2026", "广州"),
    # 社区医师 / 全科
    ("社区卫生服务中心 全科医师 招聘 2026", "东莞"),
    ("社区医院 全科医生 招聘 2026", "广州"),
    # 校医
    ("校医 招聘 事业编 2026", "东莞"),
    ("中小学 校医 招聘 2026 编制", "广州"),
    # 卫健委 / 疾控
    ("卫健委 招聘 事业编 2026", "东莞"),
    ("疾控中心 事业编 招聘 2026", "广州"),
    # AI 医疗
    ("AI 医疗 临床医学经理 招聘 2026", "广州"),
    ("医学经理 心血管 招聘 2026", "广州"),
]

# 城市白名单：入库前用此清单过滤，非白名单城市的岗位自动丢弃
ALLOWED_CITIES = ["东莞", "广州"]


def crawl_from_paste(text, source_label="手动粘贴"):
    """
    主入口：用户粘贴搜索结果文本 → 解析 → 入库
    返回 {found, inserted, duplicate, invalid, items}
    """
    items = parser.parse_bulk_lines(text)
    if not items:
        # 整页文本模式
        items = parser.parse_webpage_text(text, {"source": source_label})

    if not items:
        database.log_crawl(source_label, 0, 0, 0, status="error", error="未解析到岗位")
        return {"found": 0, "inserted": 0, "duplicate": 0, "invalid": 0, "items": []}

    # 过滤已过期
    valid_items = []
    expired = 0
    for it in items:
        if it.get("deadline"):
            exp = parser.is_likely_expired(it["deadline"])
            if exp is True:
                expired += 1
                continue
        # URL 必须以 http 开头
        if not it.get("url", "").startswith(("http://", "https://")):
            continue
        valid_items.append(it)

    result = database.add_jobs_bulk(valid_items)
    database.log_crawl(
        source_label,
        len(items),
        result["inserted"],
        result["duplicate"] + result["invalid"],
        status="ok",
    )
    return {
        "found": len(items),
        "expired_filtered": expired,
        "inserted": result["inserted"],
        "duplicate": result["duplicate"],
        "invalid": result["invalid"],
        "items": valid_items[:10],
    }


def fetch_url_summary(url, timeout=10):
    """抓取一个 URL 的网页标题、文本摘要（用户输入 URL 自动预填表单）"""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}", "url": url}
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        title = (soup.title.string if soup.title else "").strip()
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        body_text = soup.get_text("\n", strip=True)[:3000]
        publish, deadline = parser.extract_dates(body_text)
        category = parser.categorize(title + " " + body_text[:500])
        cities = parser.detect_cities(title + " " + body_text[:500])
        reliability = parser.detect_reliability(url, title)
        has_bianzhi = parser.detect_bianzhi(body_text[:1000])
        return {
            "title": title or "未知岗位",
            "description": body_text[:500],
            "publish_date": publish,
            "deadline": deadline,
            "category": category,
            "city": (cities or [""])[0],
            "reliability": reliability,
            "has_bianzhi": has_bianzhi,
            "url": url,
        }
    except Exception as e:
        return {"error": str(e), "url": url}


def _tavily_search_one(query, max_results=8, days=60):
    """
    调一次 Tavily 搜索，返回 results 列表。
    days 用于 server-side 时间过滤（只搜最近 N 天，避免远古岗位）。
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "include_raw_content": False,
                "max_results": max_results,
                "days": days,
                "topic": "general",
            },
            timeout=25,
        )
        if r.status_code != 200:
            return None
        return r.json().get("results", [])
    except Exception:
        return None


def search_tavily_for_jobs(queries=None, days=60, max_per_query=8):
    """
    用 Tavily 自动搜索一组关键词，把每条结果解析成岗位结构化字段，
    过滤已过期，再批量入库。
    返回汇总 dict（插入数/重复数/失败数/每条结果）。
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "未配置 TAVILY_API_KEY，请先在环境变量里设置"}

    queries = queries or DEFAULT_SEARCH_QUERIES
    all_results = []
    seen_urls = set()
    summary_per_query = []
    skipped_low_quality = []  # 信源过滤：被丢弃的"待审"噪音

    for query, city in queries:
        results = _tavily_search_one(query, max_results=max_per_query, days=days)
        if results is None:
            summary_per_query.append({"query": query, "city": city, "count": 0, "error": True})
            continue
        # 每条结果尝试解析成岗位
        for res in results:
            url = res.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = res.get("title", "")
            content = res.get("content", "")
            if not title:
                continue

            # === 信源白名单过滤（防噪音） ===
            reliability = parser.detect_reliability(url, title)
            if reliability == "待审":
                # Tavily 对宽泛关键词常召回"医院首页/机构名单"等无关页面，
                # 这些页面的 content 片段无法被判别为岗位，直接丢弃。
                skipped_low_quality.append({
                    "url": url,
                    "title": title[:60],
                    "reason": "信源等级=待审（非.gov.cn/招聘平台/医院关键词）",
                })
                continue
            # === 过滤结束 ===

            # 把 Tavily 拿到的结构化文本喂给 parser
            blob = f"{title} | {url}\n{content}"
            items = parser.parse_bulk_lines(blob)
            if not items:
                items = parser.parse_webpage_text(blob, {"source": "tavily"})
            if items:
                # 把 city 强制设为查询对应的城市
                for it in items:
                    if not it.get("city"):
                        it["city"] = city
                    it["source"] = f"tavily:{query}"
                all_results.extend(items)
        summary_per_query.append({
            "query": query, "city": city,
            "count": len(results) if results else 0,
        })
        time.sleep(0.3)  # 礼貌限速

    if not all_results:
        database.log_crawl(
            "tavily_auto", len(queries), 0, 0,
            status="ok", error="所有关键词无结果",
        )
        return {
            "inserted": 0, "duplicate": 0, "invalid": 0,
            "queries": summary_per_query,
            "items": [],
            "skipped_low_quality": skipped_low_quality[:10],
            "note": "搜索完成，但未解析到结构化岗位（可能所有结果被信源过滤掉了，或 Tavily 结果不够结构化）。",
        }

    # 过滤过期 + URL 合法 + 城市白名单
    valid_items = []
    expired = 0
    skipped_wrong_city = 0
    for it in all_results:
        if it.get("deadline"):
            if parser.is_likely_expired(it["deadline"]) is True:
                expired += 1
                continue
        if not it.get("url", "").startswith(("http://", "https://")):
            continue
        # 城市白名单过滤：检测标题+内容里的城市，若出现非白名单城市则丢弃
        # （Tavily 搜"东莞 心电图"也可能召回深圳/上海的招聘）
        city_in_text = parser.detect_cities(
            it.get("title", "") + " " + it.get("hospital", "") + " " + it.get("source", "")
        )
        wrong_city = [c for c in city_in_text if c not in ALLOWED_CITIES]
        if wrong_city:
            skipped_wrong_city += 1
            continue
        valid_items.append(it)

    # 去重（数据库内部还会再按 URL 去重一次）
    seen = set()
    deduped = []
    for it in valid_items:
        u = it.get("url", "")
        if u in seen:
            continue
        seen.add(u)
        deduped.append(it)

    result = database.add_jobs_bulk(deduped)
    database.log_crawl(
        "tavily_auto",
        len(all_results),
        result["inserted"],
        result["duplicate"] + result["invalid"],
        status="ok",
    )
    return {
        "queries": summary_per_query,
        "found": len(all_results),
        "skipped_low_quality_count": len(skipped_low_quality),
        "skipped_low_quality_samples": skipped_low_quality[:5],
        "skipped_wrong_city": skipped_wrong_city,
        "expired_filtered": expired,
        "inserted": result["inserted"],
        "duplicate": result["duplicate"],
        "invalid": result["invalid"],
        "items": deduped[:20],
    }


def check_url_alive(url, timeout=8):
    """检查 URL 是否仍可访问"""
    if not url:
        return None
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if r.status_code in (405, 403):
            r = requests.get(url, timeout=timeout, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, stream=True)
            r.close()
        return r.status_code < 400
    except Exception:
        return False


def sweep_expired():
    """扫描全库，把已过期岗位标 expired"""
    with database.get_db() as conn:
        rows = conn.execute(
            "SELECT id, deadline FROM jobs WHERE status='active' AND deadline IS NOT NULL"
        ).fetchall()
    updated = 0
    for r in rows:
        if parser.is_likely_expired(r["deadline"]) is True:
            database.update_job(r["id"], {"status": "expired"})
            updated += 1
    return updated


def sweep_dead_links(sample_size=80):
    """巡检所有 active 岗位的 URL，404/410 标 expired（不抽检前 N 条以避免卡顿）"""
    with database.get_db() as conn:
        rows = conn.execute(
            "SELECT id, url FROM jobs WHERE status='active' "
            "ORDER BY last_checked_at IS NULL DESC, last_checked_at ASC LIMIT ?",
            (sample_size,),
        ).fetchall()
    expired = 0
    checked = 0
    for r in rows:
        checked += 1
        alive = check_url_alive(r["url"])
        with database.get_db() as conn:
            if alive is False:
                conn.execute(
                    "UPDATE jobs SET status='expired', last_checked_at=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), r["id"]),
                )
                expired += 1
            else:
                conn.execute(
                    "UPDATE jobs SET last_checked_at=? WHERE id=?",
                    (datetime.now().isoformat(timespec="seconds"), r["id"]),
                )
    return {"checked": checked, "expired": expired, "queue_remaining": "next run"}


# ============ 后台定时任务（仅云端部署时启用）============

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler_if_enabled():
    """在云端环境变量 ENABLE_SCHEDULER=1 时启动后台线程，每日自动 Tavily 搜索"""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return False
        if os.environ.get("ENABLE_SCHEDULER") != "1":
            return False
        if not os.environ.get("TAVILY_API_KEY"):
            return False
        _scheduler_started = True
        threading.Thread(target=_scheduler_loop, daemon=True).start()
        return True


def _scheduler_loop():
    """每日 08:00 自动跑一次"""
    last_run_date = None
    while True:
        now = datetime.now()
        if now.hour == 8 and now.date() != last_run_date:
            try:
                search_tavily_for_jobs()
                sweep_expired()
            except Exception:
                pass
            last_run_date = now.date()
        time.sleep(600)  # 10 分钟检查一次


if __name__ == "__main__":
    database.init_db()
    if os.environ.get("TAVILY_API_KEY"):
        out = search_tavily_for_jobs()
        print(json.dumps(out, ensure_ascii=False, indent=2)[:2000])
    else:
        # 没 key 时跑手动粘贴自检
        sample = """体检科医师 FY007 | 东莞市妇幼保健院 | https://dghb.dg.gov.cn/post_xxx.html
心电图医师 FY010 | 东莞市妇幼保健院 | https://example.org/post_yyy.html
发布日期：2026-07-01
截止日期：2026-11-30
"""
        print(crawl_from_paste(sample, source_label="自测"))
    print("过期扫描：", sweep_expired())
    print("统计：", database.stats())
