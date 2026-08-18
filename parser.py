"""
文本解析器 - 岗位雷达小程序
支持从以下来源解析岗位：
1. 用户粘贴的逐行搜索结果
2. 用户粘贴的网页全文
3. 用户手动输入结构化字段
"""
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

# 类别关键词映射
CATEGORY_KEYWORDS = {
    "体检科": ["体检", "健康管理中心", "健康管理科", "健康体检中心", "体检中心"],
    "心电图": ["心电图"],
    "社区医师": ["社区", "全科医师", "全科医生", "社区医师", "社卫"],
    "校医": ["校医", "学校医师", "校园医生", "中小学卫生"],
    "卫健委": ["卫健委", "卫生健康局", "卫生健康委员会"],
    "疾控中心": ["疾控", "疾病预防控制", "卫生监督"],
    "AI医疗": [
        "AI医疗", "医疗AI", "医学AI", "医疗科技", "数字医疗",
        "智能医疗", "互联网医疗", "互联网医院",
    ],
}

# 城市列表（按优先级匹配）
CITY_KEYWORDS = [
    "东莞", "深圳", "广州", "惠州", "佛山", "中山", "珠海",
    "江门", "肇庆", "清远", "韶关", "汕头", "潮州", "揭阳", "汕尾",
    "梅州", "河源", "阳江", "茂名", "湛江", "云浮",
    "上海", "北京", "杭州", "南京", "苏州", "成都", "重庆",
]

# 省份/外省城市关键词（用于过滤非东莞/广州的岗位）
# 当 title/hospital 里出现这些词时，说明岗位不在目标城市
NON_TARGET_REGION_KEYWORDS = [
    # 省份
    "福建", "浙江", "江苏", "湖南", "湖北", "江西", "河南", "河北",
    "山东", "山西", "陕西", "安徽", "四川", "辽宁", "吉林", "黑龙江",
    "云南", "贵州", "甘肃", "青海", "海南", "台湾",
    "北京", "上海", "天津", "重庆",
    # 省会/大中城市
    "杭州", "南京", "苏州", "成都", "武汉", "长沙", "郑州", "济南",
    "合肥", "福州", "南昌", "石家庄", "太原", "沈阳", "长春", "哈尔滨",
    "昆明", "贵阳", "兰州", "西宁", "海口", "南宁", "拉萨", "乌鲁木齐",
    "银川", "呼和浩特",
    # 广东省内非目标城市
    "深圳", "珠海", "佛山", "惠州", "中山", "江门", "肇庆",
]

# 可靠性判断关键词
OFFICIAL_KEYWORDS = [
    "人民医院", "中心医院", "附属医院",
    "中医院", "妇幼保健", "卫健委", "疾控中心", "教育局",
    "卫生健康局", "人社局", "事业单位",
]  # 注意：detect_reliability() 不再用此列表做信源判定，仅保留作其他可能用途

THIRD_PARTY_DOMAINS = [
    "jobmd", "kq36", "fenbi", "51jOB", "yingjiesheng", "yingjishi",
    "dxy", "zhongh", "zhonghr", "medical", "yisheng", "yixue",
    "boss", "zhipin", "liepin", "lagou", "zhaopin", "51job",
]


def categorize(text):
    """根据文本推断岗位类别"""
    t = text or ""
    for cat, kws in CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return cat
    return "其他"


def detect_cities(text):
    """从文本中识别所有出现的城市"""
    found = []
    for c in CITY_KEYWORDS:
        if c in text:
            found.append(c)
    return found


def detect_reliability(url, title=""):
    """判断信息可靠性：官方 / 第三方 / 待审

    收紧版：仅信任政府/教育域名和主流招聘平台。
    不再因标题含"中心医院/卫健委"等关键词就标为官方——
    因为 Tavily 召回片段太短，标题里出现关键词不等于页面就是岗位公告。
    副作用：医院官网（xxx-hospital.com.cn）的招聘页会被判为"待审"
            并被 Tavily 自动搜索过滤掉；这类岗位通常也会在 .gov.cn 同步发布。
    """
    u = (url or "").lower()
    # 官方域名（政府/教育）
    if ".gov.cn" in u or ".edu.cn" in u:
        return "官方"
    # 第三方平台（招聘网站）
    for d in THIRD_PARTY_DOMAINS:
        if d in u:
            return "第三方"
    return "待审"


def detect_bianzhi(text):
    """检测是否包含编制信息"""
    t = text or ""
    if any(k in t for k in ["事业编制", "编制内", "事业编", "入编"]):
        return True
    if any(k in t for k in ["纳入岗位管理的编制外", "编制外", "合同制", "劳务派遣"]):
        return False
    return False


# 各种日期格式
DATE_PATTERNS = [
    (r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", "%Y-%m-%d"),
    (r"(\d{4})[年\-/](\d{1,2})[月]", "%Y-%m"),
]

DEADLINE_KEYWORDS = ["截止", "截止日期", "报名截止", "报名时间", "报名期限", "报名起止", "考试时间"]
PUBLISH_KEYWORDS = ["发布日期", "发布时间", "公告时间", "时间："]


def normalize_date(year, month, day=None):
    """把日期数字统一为 YYYY-MM-DD"""
    y, m, d = int(year), int(month), int(day) if day else 1
    if not (2000 < y < 2100) or not (1 <= m <= 12) or (day and not 1 <= d <= 31):
        return None
    if day:
        try:
            return datetime(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return datetime(y, m, d).strftime("%Y-%m-%d")


def extract_dates(text):
    """
    从一段文本里提取发布日期和截止日期。
    返回 (publish_date, deadline) 都是 YYYY-MM-DD 或 None。
    """
    if not text:
        return None, None

    # 截止日期：找带关键词的最近一个日期
    deadline = None
    publish_date = None

    # 切行
    lines = text.replace("\r", "\n").split("\n")

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        # 找截止日期
        if any(k in line_clean for k in DEADLINE_KEYWORDS):
            m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", line_clean)
            if m:
                d = normalize_date(*m.groups())
                if d:
                    deadline = d
        # 找发布日期
        elif any(k in line_clean for k in PUBLISH_KEYWORDS):
            m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", line_clean)
            if m:
                d = normalize_date(*m.groups())
                if d:
                    publish_date = d
        # 找到 "报名时间：2026-08-01 至 2026-08-15" 这种格式
        elif "报名时间" in line_clean or "报名起止" in line_clean:
            ms = re.findall(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", line_clean)
            if len(ms) >= 1:
                d = normalize_date(*ms[0])
                if d and not publish_date:
                    publish_date = d
            if len(ms) >= 2:
                d = normalize_date(*ms[1])
                if d:
                    deadline = d

    # 兜底：找全文里最早的两个日期
    if not publish_date and not deadline:
        all_matches = re.findall(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
        if all_matches:
            parsed = [normalize_date(*m) for m in all_matches if normalize_date(*m)]
            if parsed:
                parsed_sorted = sorted(set(parsed))
                publish_date = parsed_sorted[0]
                if len(parsed_sorted) > 1:
                    deadline = parsed_sorted[-1]

    return publish_date, deadline


URL_REGEX = re.compile(r'https?://[^\s\)\]\，"\'<>]+', re.IGNORECASE)
HOST_RE = re.compile(r"https?://([^/]+)")


def extract_urls(text):
    """从文本里抽取所有 URL，按出现顺序"""
    if not text:
        return []
    return list(dict.fromkeys(URL_REGEX.findall(text)))  # 保序去重


def parse_line_input(line):
    """
    解析单行输入。支持的格式：
    - 标题 | 医院 | URL
    - 标题\t医院\tURL
    - 标题 - 医院 - URL
    - URL（仅 URL，前后无标题）
    """
    line = (line or "").strip()
    if not line:
        return None

    # 提取 URL
    urls = extract_urls(line)
    url = urls[0] if urls else ""

    # 去掉 URL
    # 去掉 URL（用单独的字符类，逐个列出要排除的字符）
    rest = re.sub(r'https?://[^\s\)\]\,"\'<>]+', "", line).strip()

    parts = [p.strip() for p in re.split(r"\s*[|\t\-]\s*", rest) if p.strip()]
    title = parts[0] if parts else ""
    hospital = parts[1] if len(parts) >= 2 else ""

    if not title and url:
        # 没有标题就用 URL 当标题
        title = f"未知岗位（{HOST_RE.match(url).group(1) if HOST_RE.match(url) else url}）"

    if not url and title:
        return {"title": title, "hospital": hospital, "url": None}

    return {"title": title, "hospital": hospital, "url": url}


def parse_bulk_lines(text):
    """
    批量解析：用户粘贴多行，每行一条岗位。
    返回岗位字典列表，自动分类、识别城市、判可靠性。
    """
    if not text:
        return []
    out = []
    seen_urls = set()
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_line_input(line)
        if not parsed or not parsed.get("url"):
            continue
        if parsed["url"] in seen_urls:
            continue
        seen_urls.add(parsed["url"])
        out.append({
            **parsed,
            "category": categorize(parsed["title"] + " " + parsed["hospital"]),
            "city": (detect_cities(parsed["title"] + " " + parsed["hospital"]) or [""])[0],
            "reliability": detect_reliability(parsed["url"], parsed["title"] + " " + parsed["hospital"]),
            "has_bianzhi": detect_bianzhi(parsed["title"] + " " + parsed["hospital"]),
            "publish_date": None,
            "deadline": None,
            "source": "手动粘贴",
        })
    return out


def parse_webpage_text(text, base_info=None):
    """
    从整段网页文本解析岗位列表。
    策略：识别每个 URL 周围的标题、医院、日期信息。
    """
    base_info = base_info or {}
    urls = extract_urls(text)
    if not urls:
        return []

    out = []
    seen = set()
    lines = text.replace("\r", "\n").split("\n")

    # 对每个 URL，在它前后 3 行内找标题
    for url in urls:
        if url in seen:
            continue
        seen.add(url)

        # 找 URL 所在行号
        url_line_idx = -1
        for i, line in enumerate(lines):
            if url in line:
                url_line_idx = i
                break
        if url_line_idx < 0:
            continue

        # 前后 3 行
        context_lines = lines[max(0, url_line_idx - 3): url_line_idx + 1]
        context_lines = [l.strip() for l in context_lines if l.strip() and url not in l]

        title = ""
        hospital = ""
        for cl in context_lines:
            if not title and 5 < len(cl) < 80 and not cl.startswith(("http", "时间")):
                title = cl
                break

        # 全文搜发布时间、截止日期
        publish_date, deadline = extract_dates(text)

        combined = title + " " + hospital + " " + (base_info.get("page_title", "") if base_info else "")
        out.append({
            "title": title or base_info.get("default_title", "未知岗位"),
            "hospital": hospital or "",
            "url": url,
            "category": categorize(combined),
            "city": (detect_cities(combined) or [base_info.get("default_city", "")])[0],
            "reliability": detect_reliability(url, combined),
            "has_bianzhi": detect_bianzhi(combined),
            "publish_date": publish_date,
            "deadline": deadline,
            "description": text[:500] if text else None,
            "source": base_info.get("source", "网页解析") if base_info else "网页解析",
        })

    return out


def is_likely_expired(deadline):
    """判断岗位是否已过期（截止日期早于今天）"""
    if not deadline:
        return None  # 未知
    try:
        d = datetime.strptime(deadline, "%Y-%m-%d")
        return d.date() < datetime.now().date()
    except Exception:
        return None


if __name__ == "__main__":
    # 简单自测
    sample = """体检科医师 FY007 | 东莞市妇幼保健院 | https://dghb.dg.gov.cn/post_xxx.html
心电图医师 FY010 | 东莞市妇幼保健院 | https://example.org/post_yyy.html
"""
    jobs = parse_bulk_lines(sample)
    for j in jobs:
        print(j)
    print("---")
    sample2 = """
某三甲医院2026年第一期招聘公告
发布日期：2026-08-01
报名截止：2026-11-30
详见：https://dghb.dg.gov.cn/post_aaa.html
联系电话：0769-12345678
"""
    print(extract_dates(sample2))
    print(parse_webpage_text(sample2, {"page_title": "招聘"}))
