"""
医疗岗位雷达 - 每日数据抓取脚本（静态 PWA 版）
从 Tavily 搜索东莞/广州医疗岗位，清洗后写入 pwa/jobs.json。
设计为独立脚本，可被 GitHub Actions 定时调用，不依赖 Flask。
"""
import json
import os
import sys
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 引入仓库根目录的 parser.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import parser

# Tavily 搜索关键词组合（8 类岗位 × 东莞/广州）
DEFAULT_SEARCH_QUERIES = [
    # 体检科 / 健康管理科
    ("体检科医师 招聘 2026", "东莞"),
    ("健康管理中心医师 招聘 2026", "东莞"),
    ("健康管理科医师 招聘 2026", "东莞"),
    ("体检科医师 招聘 2026", "广州"),
    ("健康管理科医师 招聘 2026 编制", "广州"),
    # 心电图
    ("心电图医师 招聘 2026", "东莞"),
    ("心电图室医生 招聘 2026", "广州"),
    # 社区医师 / 全科
    ("社区卫生服务中心 全科医师 招聘 2026", "东莞"),
    ("社区医院 全科医生 招聘 2026", "广州"),
    # 心血管内科
    ("心血管内科医师 招聘 2026", "东莞"),
    ("心血管内科医生 招聘 2026", "广州"),
    # 校医
    ("校医 招聘 事业编 2026", "东莞"),
    ("中小学 校医 招聘 2026 编制", "广州"),
    # 卫健委 / 疾控
    ("卫健委 招聘 事业编 2026", "东莞"),
    ("疾控中心 事业编 招聘 2026", "广州"),
    # AI 医疗 / 医学经理
    ("AI 医疗 临床医学经理 招聘 2026", "广州"),
    ("医学经理 心血管 招聘 2026", "广州"),
    # 定向官方渠道（提高具体公告命中率，减少聚合页噪音）
    ("东莞市卫生健康局 招聘公告 2026", "东莞"),
    ("东莞市公立医院 公开招聘 2026年", "东莞"),
    ("东莞市教育局 校医 招聘 2026", "东莞"),
    ("广州市卫生健康委员会 公开招聘 2026", "广州"),
    ("广州市市属事业单位 医疗卫生 招聘公告 2026", "广州"),
]

ALLOWED_CITIES = ["东莞", "广州"]
PWA_DIR = os.path.join(ROOT, "pwa")
JOBS_FILE = os.path.join(PWA_DIR, "jobs.json")

# ── 聚合页/频道页识别（点进去是全国混着的岗位列表，不是具体招聘公告） ──
AGG_URL_PATTERNS = [
    "gaoxiaojob.com/hotword/",       # 高校人才网"XX招聘汇总"页（全国）
    "gaoxiaojob.com/rczhaopin/",     # 高校人才网人才招聘频道页
    "gaoxiaojob.com/company/",       # 高校人才网机构主页/招聘专区（岗位聚合）
    "gaoxiaojob.com/zhaopin/",       # 高校人才网招聘频道页
    "liepin.com/zp",                 # 猎聘聚合页（/zp拼音 串）；具体职位页是 /job/ 开头
    "jobmd.cn/zhaopin/",             # 丁香人才频道页（具体职位是 /work/）
    "yzp.cn/zhaopingonggao",         # 医招网公告列表页
    "med66.com",                     # 医学教育网全国卫生事业编汇总
    "wjw.gz.gov.cn/xxgk/",           # 卫健委人事信息栏目页（列表非具体公告）
    "/gkmlpt/index",                 # 信息公开平台首页/栏目页
]
AGG_TITLE_PATTERNS = [
    "招聘信息汇总", "招聘信息】", "招聘网_", "_最新", "招聘公告_", "汇总",
    "工作职位/岗位", "人才招聘引进专区",
]
# 泛化标题（抓不到具体岗位名，点进去多为栏目页/结果页）
GENERIC_TITLES = {"公告公示", "人事信息", "通知公告", "招聘信息", "公示", "就业机会"}

# 标题含这些词的不是社会招聘岗位（定向培养是高考招生项目等）
NON_JOB_TITLE_KWS = ["订单定向培养", "定向培养医学", "招生计划"]

# 结果公示类关键词（招聘已结束，页面是拟聘用/成绩公示，不是在招岗位）
# 注意：不要用"体检考察"这类词——正常招聘公告的流程描述里也有"体检、考察"
RESULT_NOTICE_KWS = ["拟聘用", "聘用公示", "成绩公示", "拟聘人员"]

# 陈旧公告阈值：无未来截止日期 + 发布超过该天数 -> 视为过期剔除
STALE_DAYS = 45

# 初始种子数据（当 jobs.json 不存在或 Tavily 失败时仍有内容展示）
SEED_JOBS = [
    {
        "title": "体检科医师 FY007",
        "hospital": "东莞市妇幼保健院",
        "city": "东莞",
        "category": "体检科",
        "url": "https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4494129.html#FY007",
        "source": "官方公告",
        "publish_date": "2026-02-01",
        "deadline": "2026-11-30",
        "has_bianzhi": False,
        "reliability": "官方",
        "description": "内科学硕士，副主任医师以上，50周岁以下。体检科通常为白班、无夜班。",
    },
    {
        "title": "心电图医师 FY010",
        "hospital": "东莞市妇幼保健院",
        "city": "东莞",
        "category": "心电图",
        "url": "https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4494129.html#FY010",
        "source": "官方公告",
        "publish_date": "2026-02-01",
        "deadline": "2026-11-30",
        "has_bianzhi": False,
        "reliability": "官方",
        "description": "心血管内科学硕士，主治医师以上，40周岁以下。心电图室值班远少于临床内科。",
    },
    {
        "title": "内科医师 FY019",
        "hospital": "东莞市妇幼保健院",
        "city": "东莞",
        "category": "社区医师",
        "url": "https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4494129.html#FY019",
        "source": "官方公告",
        "publish_date": "2026-02-01",
        "deadline": "2026-11-30",
        "has_bianzhi": False,
        "reliability": "官方",
        "description": "内科学硕士，医师以上，35周岁以下，需完成住院医师规范化培训。",
    },
]

# ── 链接体检 ─────────────────────────────────────────────
# 返回 "ok"（可访问）/ "dead"（确认失效：404/410 或内容报错）/ "unknown"（网络波动、反爬 403 等，不判死刑）
_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_DEAD_CONTENT_KWS = [
    "页面不存在", "内容不存在", "网页无法访问", "链接已失效", "文件未找到",
    "职位已关闭", "已停止招聘", "招聘已结束", "公告不存在",
]

# 人工确认已下线/失效/过期的 URL（页面仍返回 200 但岗位实际不可投，由用户反馈或人工核查确认）
MANUAL_DEAD_URLS = {
    # 松山湖中心医院健康体检中心医师，丁香人才网页面仍在但岗位已下线（2026-08-25 用户确认）
    "https://www.jobmd.cn/work/1390912.htm",
    # 东莞市社区卫生服务中心"百万英才汇南粤"集中招聘，报名时间2026-03-16至03-20，早已截止（2026-09-06 核查确认）
    "https://dghb.dg.gov.cn/ztpd/gkzp/zpgg/content/post_4508073.html",
    # 从化区卫健局所属事业单位招聘——拟聘用人员公示（招聘已结束，2026-09-06 核查确认）
    "http://www.conghua.gov.cn/zwgk/gggs/content/post_10988167.html",
    # 东莞市卫健局集中招聘高校毕业生——入围体检人员名单公告（招聘已结束，2026-09-06 核查确认）
    "https://dghb.dg.gov.cn/gkmlpt/content/4/4530/post_4530964.html",
    # 广州市白云区卫健系统2026年第一批公开招聘，2026-07-15发布，报名早已截止（2026-09-06 核查确认）
    "https://www.by.gov.cn/zwgk/zdlyxxgkzl/jycyxxgkzl/zpxx/qnzpxx/content/post_10902933.html",
    # 广东省订单定向培养医学大学生项目通知——高考招生项目非社会招聘，且发布在云安政府网（2026-09-06 核查确认）
    "https://www.yunan.gov.cn/yfyawsj/gkmlpt/content/2/2016/post_2016174.html",
}


def check_url_alive(url):
    """检测链接是否存活。仅 404/410 或明确的失效文案才判 dead。"""
    if not url or not str(url).startswith("http"):
        return "dead"
    base_url = str(url).split("#")[0]
    if base_url in MANUAL_DEAD_URLS:
        return "dead"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=15,
            verify=False,
            allow_redirects=True,
        )
        if r.status_code in (404, 410):
            return "dead"
        if r.status_code >= 400:
            return "unknown"  # 403/5xx 可能是反爬，不判死
        text = (r.text or "")[:80000]
        for kw in _DEAD_CONTENT_KWS:
            if kw in text:
                return "dead"
        return "ok"
    except requests.exceptions.SSLError:
        return "unknown"
    except Exception:
        return "unknown"


def _drop_dead_jobs(jobs, label="existing"):
    """并发体检，剔除确认失效(dead)的岗位。unknown 的保留待下次复检。"""
    if not jobs:
        return jobs
    with ThreadPoolExecutor(max_workers=8) as ex:
        alive_flags = list(ex.map(lambda j: check_url_alive(j.get("url", "")), jobs))
    kept = []
    for j, flag in zip(jobs, alive_flags):
        if flag == "dead":
            print(f"[link-check] 剔除失效链接({label}): {j.get('title', '')[:30]} -> {j.get('url', '')[:70]}")
        else:
            kept.append(j)
    return kept


def _tavily_search_one(query, api_key, max_results=8, days=60):
    """调用 Tavily API 搜索一次。"""
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
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[tavily warn] {query} -> HTTP {r.status_code}")
            return None
        return r.json().get("results", [])
    except Exception as e:
        print(f"[tavily error] {query}: {e}")
        return None


def _parse_tavily_result(res, query):
    """把 Tavily 一条结果解析成岗位字典。"""
    url = res.get("url", "")
    title = res.get("title", "")
    content = res.get("content", "")
    if not url or not title:
        return None

    blob = f"{title} | {url}\n{content}"
    # 先按整页文本解析
    items = parser.parse_bulk_lines(blob)
    if not items:
        items = parser.parse_webpage_text(blob, {"source": "tavily"})
    if not items:
        return None

    item = items[0]
    item["source"] = f"tavily:{query}"

    # 描述兜底：Tavily 摘要有内容但 parser 没解析出 description 时，用摘要截断
    if not item.get("description") and content:
        item["description"] = content.strip()[:500]

    # 城市识别（排除 source/query 污染）
    full_text = " ".join([it or "" for it in [
        item.get("title", ""),
        item.get("hospital", ""),
        item.get("description", ""),
        content,
    ]])
    if parser.has_wrong_region(full_text):
        return None
    chosen = parser.pick_city(full_text)
    if not chosen:
        return None
    item["city"] = chosen

    # 信源
    item["reliability"] = parser.detect_reliability(url, title + " " + content[:200])
    if item["reliability"] == "待审":
        return None

    # 编制
    item["has_bianzhi"] = parser.detect_bianzhi(title + " " + content[:500])

    # 日期
    pub, ddl = parser.extract_dates(title + "\n" + content[:1500])
    if pub:
        item["publish_date"] = pub
    if ddl:
        item["deadline"] = ddl

    # 分类
    item["category"] = parser.categorize(title + " " + content[:500])

    return item


def _is_job_match_category(item):
    """确认岗位类别属于用户关注范围。"""
    cat = item.get("category", "其他")
    # 用户关注：体检科、心电图、社区、校医、心血管内科、AI医疗、卫健委、疾控中心
    allowed = ["体检科", "心电图", "社区医师", "校医", "心血管内科", "AI医疗", "卫健委", "疾控中心"]
    return cat in allowed


def _drop_expired(jobs):
    """直接剔除截止日期已过的岗位（不再保留 expired 状态，避免推荐已下线岗位）。"""
    today = datetime.now().date()
    kept = []
    for j in jobs:
        ddl = j.get("deadline")
        if ddl:
            try:
                d = datetime.strptime(str(ddl)[:10], "%Y-%m-%d").date()
                if d < today:
                    print(f"[expired] 剔除已截止: {j.get('title', '')[:30]} (deadline={ddl})")
                    continue
            except Exception:
                pass
        j["status"] = "active"
        kept.append(j)
    return kept


def _drop_wrong_city(jobs):
    """剔除城市不在 广州/东莞 范围内的岗位（含标题中出现外地城市但 city 字段误标的情况）。"""
    other_cities = [
        # 省外主要城市
        "北京", "上海", "深圳", "武汉", "长沙", "成都", "重庆", "杭州",
        "南京", "西安", "郑州", "福州", "昆明", "贵阳", "南昌", "合肥",
        "天津", "苏州", "青岛", "济南", "厦门",
        # 广东非东莞/广州城市（阳江岗位混入东莞标签等场景）
        "佛山", "惠州", "珠海", "中山", "江门", "阳江", "湛江", "茂名",
        "汕头", "梅州", "清远", "韶关", "揭阳", "潮州", "汕尾", "河源",
        "肇庆", "云浮",
    ]
    kept = []
    for j in jobs:
        title = j.get("title", "") or ""
        if j.get("city") not in ALLOWED_CITIES or any(c in title for c in other_cities):
            print(f"[city] 剔除外地岗位: {title[:30]} (city={j.get('city')})")
            continue
        kept.append(j)
    return kept


def _is_agg_job(j):
    """判断是否为聚合页/频道页/泛标题页/非招聘内容（点进去是全国岗位列表，非东莞广州具体岗位）。"""
    url = (j.get("url") or "").lower().split("#")[0]
    title = (j.get("title") or "").strip()
    if any(p in url for p in AGG_URL_PATTERNS):
        return "聚合页URL"
    # 裸域名首页（如 http://dghb.dg.gov.cn），路径为空必然不是具体岗位
    try:
        path = url.split("//", 1)[-1].split("/", 1)
        if len(path) == 1 or path[1].strip("/") == "":
            return "官网首页"
    except Exception:
        pass
    if any(p in title for p in AGG_TITLE_PATTERNS):
        return "聚合页标题"
    if title in GENERIC_TITLES:
        return "泛化标题"
    if any(k in title for k in NON_JOB_TITLE_KWS):
        return "非招聘岗位"
    return None


def _drop_agg_jobs(jobs):
    """剔除聚合页/频道页/泛标题/非招聘岗位条目。"""
    kept = []
    for j in jobs:
        why = _is_agg_job(j)
        if not why:
            blob = " ".join([j.get("title") or "", (j.get("description") or "")[:300]])
            if any(k in blob for k in NON_JOB_TITLE_KWS):
                why = "非招聘岗位"
        if why:
            print(f"[agg] 剔除{why}: {(j.get('title') or '')[:30]} -> {(j.get('url') or '')[:70]}")
            continue
        kept.append(j)
    return kept


def _drop_result_notices(jobs):
    """剔除招聘结果公示（拟聘用/成绩公示等），只留在招岗位。"""
    kept = []
    for j in jobs:
        blob = " ".join([j.get("title") or "", (j.get("description") or "")[:300]])
        if any(k in blob for k in RESULT_NOTICE_KWS):
            print(f"[notice] 剔除结果公示: {(j.get('title') or '')[:35]}")
            continue
        kept.append(j)
    return kept


def _drop_stale_jobs(jobs):
    """剔除陈旧公告：无未来截止日期，且发布时间超过 STALE_DAYS 天。

    医疗招聘公告报名窗口通常 5~15 天；发布很久又无明确长期有效期的，
    实际早已截止。有未来 deadline 的不受影响（如编外常年滚动岗位）。
    """
    today = datetime.now().date()
    kept = []
    for j in jobs:
        ddl = j.get("deadline")
        if ddl:
            try:
                d = datetime.strptime(str(ddl)[:10], "%Y-%m-%d").date()
                if d >= today:
                    kept.append(j)  # 有未来截止日期，保留
                    continue
            except Exception:
                pass
        pub = j.get("publish_date")
        if pub:
            try:
                p = datetime.strptime(str(pub)[:10], "%Y-%m-%d").date()
                if (today - p).days > STALE_DAYS:
                    print(f"[stale] 剔除陈旧公告: {(j.get('title') or '')[:32]} (发布于{pub})")
                    continue
            except Exception:
                pass
        kept.append(j)
    return kept


def fetch_jobs(api_key=None, queries=None, days=45, max_per_query=10):
    """
    主入口：搜索、清洗、合并，返回 jobs 列表。
    失败时返回 None（调用方可用种子数据兜底）。
    """
    api_key = api_key or os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("[fetch_jobs] 未配置 TAVILY_API_KEY，跳过 Tavily 抓取")
        return None

    queries = queries or DEFAULT_SEARCH_QUERIES
    all_items = []
    seen_urls = set()

    for query, city_hint in queries:
        results = _tavily_search_one(query, api_key, max_results=max_per_query, days=days)
        if not results:
            continue
        for res in results:
            url = res.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            item = _parse_tavily_result(res, query)
            if not item:
                continue
            if not item.get("city") or item["city"] not in ALLOWED_CITIES:
                continue
            if not _is_job_match_category(item):
                continue
            # 聚合页/频道页/泛标题：点进去是全国岗位列表，不收
            if _is_agg_job(item):
                print(f"[agg] 丢弃聚合页结果: {item.get('title', '')[:30]} -> {url[:70]}")
                continue
            # 结果公示（拟聘用/成绩公示）不是在招岗位，不收
            blob = " ".join([item.get("title") or "", (item.get("description") or "")[:300]])
            if any(k in blob for k in RESULT_NOTICE_KWS):
                print(f"[notice] 丢弃结果公示: {item.get('title', '')[:35]}")
                continue
            # 新岗位入库前先体检链接，死链直接丢弃
            if check_url_alive(item.get("url", "")) == "dead":
                print(f"[link-check] 新抓取结果链接失效，丢弃: {item.get('title', '')[:30]} -> {item.get('url', '')[:70]}")
                continue
            item["status"] = "active"
            all_items.append(item)
        time.sleep(0.3)

    if not all_items:
        print("[fetch_jobs] Tavily 未返回有效岗位")
        return None

    # 按 URL 去重（已按 seen_urls 去重，这里再按 title+url 保险）
    deduped = []
    keys = set()
    for it in all_items:
        key = it.get("url", "")
        if key in keys:
            continue
        keys.add(key)
        deduped.append(it)

    return deduped


def load_existing_jobs():
    """读取现有 jobs.json（含用户 localStorage 标记之外的数据）。"""
    if not os.path.exists(JOBS_FILE):
        return []
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("jobs", [])
    except Exception:
        return []


def merge_jobs(existing, new):
    """合并旧数据与新数据：新数据覆盖同 URL 旧数据，保留旧数据中不再被抓到的 URL。"""
    url_to_job = {j["url"]: j for j in existing if j.get("url")}
    # 新数据覆盖/新增
    for j in new:
        if j.get("url"):
            url_to_job[j["url"]] = j
    return list(url_to_job.values())


def build_jobs_data(tavily_items=None):
    """构建最终写入 jobs.json 的数据结构。"""
    existing = load_existing_jobs()
    # 以种子数据打底
    seed_map = {j["url"]: j for j in SEED_JOBS}
    existing_map = {j["url"]: j for j in existing if j.get("url")}

    # 合并优先级：Tavily 新数据 > 现有 > 种子
    final_map = dict(seed_map)
    final_map.update(existing_map)
    if tavily_items:
        for j in tavily_items:
            if j.get("url"):
                final_map[j["url"]] = j

    jobs = list(final_map.values())
    # 五重清理：聚合页 -> 外地 -> 结果公示 -> 已截止/陈旧 -> 死链（每日复检旧岗位）
    jobs = _drop_agg_jobs(jobs)
    jobs = _drop_wrong_city(jobs)
    jobs = _drop_result_notices(jobs)
    jobs = _drop_expired(jobs)
    jobs = _drop_stale_jobs(jobs)
    jobs = _drop_dead_jobs(jobs, label="daily")

    # 排序：编内优先，有发布日期按新到旧
    def sort_key(j):
        is_bianzhi = 1 if j.get("has_bianzhi") else 0
        pub = j.get("publish_date") or "1970-01-01"
        return (is_bianzhi, pub)

    jobs.sort(key=sort_key, reverse=True)

    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(jobs),
        "jobs": jobs,
    }


def main():
    os.makedirs(PWA_DIR, exist_ok=True)
    api_key = os.environ.get("TAVILY_API_KEY")

    new_items = fetch_jobs(api_key=api_key)
    data = build_jobs_data(new_items)

    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[done] total={data['total']} updated_at={data['updated_at']}")
    active = sum(1 for j in data["jobs"] if j.get("status") == "active")
    bianzhi = sum(1 for j in data["jobs"] if j.get("has_bianzhi"))
    print(f"       active={active} bianzhi={bianzhi}")


if __name__ == "__main__":
    main()
