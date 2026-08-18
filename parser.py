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

# 目标城市（岗位雷达只服务这两个城市）
TARGET_CITIES = ["东莞", "广州"]

# 全国主要城市列表（用于识别文本中出现的任何城市）
ALL_CHINA_CITIES = [
    # 广东
    "东莞", "深圳", "广州", "惠州", "佛山", "中山", "珠海",
    "江门", "肇庆", "清远", "韶关", "汕头", "潮州", "揭阳", "汕尾",
    "梅州", "河源", "阳江", "茂名", "湛江", "云浮",
    # 直辖市
    "上海", "北京", "天津", "重庆",
    # 华东
    "杭州", "南京", "苏州", "宁波", "温州", "无锡", "常州", "徐州",
    "南通", "盐城", "扬州", "泰州", "镇江", "淮安", "宿迁", "连云港",
    "金华", "绍兴", "嘉兴", "台州", "湖州", "衢州", "舟山", "丽水",
    "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆",
    "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城",
    "福州", "厦门", "泉州", "漳州", "莆田", "三明", "南平", "龙岩", "宁德",
    "南昌", "赣州", "九江", "宜春", "上饶", "吉安", "抚州", "景德镇", "萍乡", "新余", "鹰潭",
    "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安",
    "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽",
    # 华中
    "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州",
    "黄冈", "咸宁", "随州", "恩施",
    "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界",
    "益阳", "郴州", "永州", "怀化", "娄底", "湘西",
    "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作",
    "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店",
    # 华北
    "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水",
    "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安", "锡林郭勒", "阿拉善",
    "北京"  # 已在上面
    # 东北
    "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新",
    "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛",
    "长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边", "长白山",
    "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯",
    "七台河", "牡丹江", "黑河", "绥化", "大兴安岭",
    # 西南
    "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江",
    "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山",
    "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南",
    "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河",
    "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆",
    "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里",
    # 西北
    "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉",
    "庆阳", "定西", "陇南", "临夏", "甘南",
    "西宁", "海东", "海北", "黄南", "海南", "果洛", "玉树", "海西",
    "银川", "石嘴山", "吴忠", "固原", "中卫",
    "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞",
    "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子",
    # 华南其他
    "海口", "三亚", "三沙", "儋州", "五指山", "琼海", "文昌", "万宁", "东方",
    "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林",
    "百色", "贺州", "河池", "来宾", "崇左",
]

# 非目标省份/城市关键词（用于过滤非东莞/广州的岗位）
# 当 title/hospital/content 里出现这些词时，说明岗位不在目标城市
NON_TARGET_REGION_KEYWORDS = [
    # 外省省份（广东除外）
    "福建", "浙江", "江苏", "湖南", "湖北", "江西", "河南", "河北",
    "山东", "山西", "陕西", "安徽", "四川", "辽宁", "吉林", "黑龙江",
    "云南", "贵州", "甘肃", "青海", "海南", "台湾", "新疆", "西藏", "宁夏",
    "内蒙古", "广西",
    # 直辖市（非广州）
    "北京", "上海", "天津", "重庆",
    # 省会/大中城市（非广州）
    "杭州", "南京", "苏州", "成都", "武汉", "长沙", "郑州", "济南",
    "合肥", "福州", "南昌", "石家庄", "太原", "沈阳", "长春", "哈尔滨",
    "昆明", "贵阳", "兰州", "西宁", "海口", "南宁", "拉萨", "乌鲁木齐",
    "银川", "呼和浩特", "西安", "宁波", "厦门", "青岛", "大连",
    # 广东省内非目标城市
    "深圳", "珠海", "佛山", "惠州", "中山", "江门", "肇庆", "清远",
    "韶关", "汕头", "潮州", "揭阳", "汕尾", "梅州", "河源", "阳江",
    "茂名", "湛江", "云浮",
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
    for c in ALL_CHINA_CITIES:
        if c in text:
            found.append(c)
    return found


def detect_target_cities(text):
    """只识别目标城市（东莞/广州）"""
    return [c for c in TARGET_CITIES if c in text]


def has_wrong_region(text):
    """
    判断文本是否明确指向非目标城市/省份。
    规则：
    1. 若同时出现目标城市（东莞/广州）和非目标省份/城市，通常仍视为目标岗位（可能是对比/迁移类信息），返回 False；
    2. 若未出现目标城市，但出现非目标省份/城市，则明确为非目标岗位，返回 True；
    3. 若未出现目标城市也未出现非目标地区，视为地点不明，返回 True（按严格策略丢弃，避免泛化招聘聚合页）。
    """
    if not text:
        return True
    has_target = bool(detect_target_cities(text))
    has_non_target = any(kw in text for kw in NON_TARGET_REGION_KEYWORDS)
    if has_target:
        # 有目标城市，允许保留，即使顺带提到非目标城市（如"深圳/广州"对比）
        return False
    if has_non_target:
        # 无目标城市，但有非目标地区，明确丢弃
        return True
    # 完全没有地区信息，也丢弃（避免"全国招聘信息网"这类聚合页）
    return True


def pick_city(text):
    """
    从文本中挑选最可能的城市。只返回东莞或广州；
    若两者都出现，按在文本中首次出现的顺序返回。
    """
    if not text:
        return ""
    first_pos = None
    chosen = ""
    for c in TARGET_CITIES:
        pos = text.find(c)
        if pos != -1 and (first_pos is None or pos < first_pos):
            first_pos = pos
            chosen = c
    return chosen


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
