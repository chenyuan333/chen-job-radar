"""
医疗岗位雷达 - 每日数据抓取脚本（静态 PWA 版）
从 Tavily 搜索东莞/广州医疗岗位，清洗后写入 pwa/jobs.json。
设计为独立脚本，可被 GitHub Actions 定时调用，不依赖 Flask。
"""
import json
import os
import re
import sys
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urljoin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 引入仓库根目录的 parser.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import parser

# Tavily 搜索关键词组合（8 类岗位 × 东莞/广州）
DEFAULT_SEARCH_QUERIES = [
    # ⚠ 配额纪律（2026-10-12 起）：Tavily 免费额度 1000 credits/月，advanced 约 2 credits/次。
    # 18 个官方栏目（OFFICIAL_FEEDS）已覆盖 广州/东莞 市·区两级事业单位与卫健系统公告，
    # 因此这里只保留"官网抓不到"的补漏查询，严格控制在 12 条/天：
    #   12 条 × 30 天 × 2 credits ≈ 720 credits/月，留出 28% 余量给手工调试。
    # 已删除：东莞市卫健局/公立医院、广州卫健委/市属/各区卫健系统、松山湖中心医院
    #         —— 这些已由官方栏目直抓稳定覆盖，重复搜索纯属浪费配额。
    # 体检科 / 健康管理科
    ("体检科医师 招聘 2026", "东莞"),
    ("体检科 健康管理科医师 招聘 2026", "广州"),
    # 心电图
    ("心电图医师 招聘 2026", "东莞"),
    ("心电图室医生 招聘 2026", "广州"),
    # 社区医师 / 全科
    ("社区卫生服务中心 全科医师 招聘 2026", "东莞"),
    ("社区医院 全科医生 招聘 2026", "广州"),
    # 心血管内科
    ("心血管内科医师 招聘 2026", "东莞"),
    ("心血管内科医生 招聘 2026", "广州"),
    # 校医（中小学编制校医走教育局/学校渠道，不在卫健系统栏目里）
    ("校医 招聘 事业编 2026", "东莞"),
    ("中小学 校医 招聘 2026 编制", "广州"),
    # AI 医疗 / 医学经理（企业岗，官网无栏目可抓）
    ("AI 医疗 临床医学经理 招聘 2026", "广州"),
    # 松山湖片区定向（用户在松山湖居住；社卫中心站点 ssl.dg.gov.cn 为 JS 渲染，
    # 列表页抓不到，只能靠搜索兜底。松山湖中心医院公告走卫健局官网，已由官方源覆盖）
    ("松山湖 社区卫生服务中心 招聘 编制外人员 公告", "东莞"),
]

ALLOWED_CITIES = ["东莞", "广州"]
PWA_DIR = os.path.join(ROOT, "pwa")
JOBS_FILE = os.path.join(PWA_DIR, "jobs.json")

# ── 聚合页/频道页识别（点进去是全国混着的岗位列表，不是具体招聘公告） ──
AGG_URL_PATTERNS = [
    "gaoxiaojob.com/hotword/",       # 高校人才网"XX招聘汇总"页（全国）
    "gaoxiaojob.com/rczhaopin/",     # 高校人才网人才招聘频道页
    "gaoxiaojob.com/company/",       # 高校人才网机构主页/招聘专区（岗位聚合）
    "gaoxiaojob.com/column/",        # 高校人才网"XX专区"栏目聚合页（全国双一流/本科高校专区等）
    "gaoxiaojob.com/zhaopin/",       # 高校人才网招聘频道页
    "gaoxiaojob.com/announcement/job-list",  # 高校人才网职位列表聚合页（一次列多单位岗位）
    "gaoxiaojob.com/job/",           # 高校人才网单个职位转载页（官方源已覆盖，避免重复推荐）
    "fenbi.com/page/positions",      # 粉笔岗位/职位表列表页（聚合多个单位岗位）
    "fenbi.com/page/fenxiaozhaokao",  # 粉笔分校招考页
    "liepin.com/zp",                 # 猎聘聚合页（/zp拼音 串）；具体职位页是 /job/ 开头
    "jobmd.cn/zhaopin/",             # 丁香人才频道页（具体职位是 /work/）
    "zhaopin.com/sou/",              # 智联招聘搜索/聚合页（/sou/ 开头是搜索结果列表）
    "liepin.com/company/",            # 猎聘企业主页（岗位聚合，且无报名窗口）
    "m.liepin.com/",                 # 猎聘移动版企业页/聚合页
    "ssl.dg.gov.cn/sslchs/",         # 松山湖社区卫生服务中心"下属单位专栏"页（栏目介绍，非招聘公告）
    "zhipin.com",                    # BOSS直聘（岗位聚合页，点进去是全国/混合岗位列表）
    "lagou.com",                     # 拉勾网（聚合页，且多为非医师岗）
    "kq36.com",                      # 康强医疗人才网（聚合页，所辖岗位多为历史批次，页面常标"已结束"）
    "jrzp.com",                      # 今日招聘网（转载聚合站，时效不可信）
    "wondercv.com",                  # 简历网站的职业科普/求职指南文章，非招聘
    "yzp.cn/zhaopingonggao",         # 医招网公告列表页
    "med66.com",                     # 医学教育网全国卫生事业编汇总
    "/gkmlpt/index",                 # 信息公开平台首页/栏目页
]
# 注意：不要再按"整段路径"拉黑政府网站栏目，例如曾用 "wjw.gz.gov.cn/xxgk/" 拉黑
# 广州市卫健委人事信息栏目页，结果把 wjw.gz.gov.cn/xxgk/rsxx/content/post_XXXX.html
# 这类**真实公告详情页**一起杀掉了 → 改为下面的"栏目页URL"通用判定。
# 第三方人才网域名：条目无任何日期（发布/截止）时无法验证时效，一律不收
THIRDPARTY_HOSTS = (
    "gaoxiaojob.com", "fenbi.com", "liepin.com", "jobmd.cn", "zhaopin.com",
    "kq36.com", "jrzp.com", "yzp.cn", "med66.com", "51job.com", "wondercv.com",
    "zhipin.com", "lagou.com", "yixuezp.com",
)
AGG_TITLE_PATTERNS = [
    "招聘信息汇总", "招聘信息】", "招聘网_", "_最新", "招聘公告_", "汇总",
    "工作职位/岗位", "人才招聘引进专区", "职位列表", "招聘岗位表", "专区",
]
# 泛化标题（抓不到具体岗位名，点进去多为栏目页/结果页）
GENERIC_TITLES = {"公告公示", "人事信息", "通知公告", "招聘信息", "公示", "就业机会", "校医", "医师", "医生"}

# 标题含这些词的不是社会招聘岗位（定向培养是高考招生项目、答复函是政务文件、求职指南是文章等）
NON_JOB_TITLE_KWS = [
    "订单定向培养", "定向培养医学", "招生计划",
    "答复的函", "建议答复", "答复函", "人大建议", "政协提案", "信访",
    "求职指南", "如何判断", "如何选择", "面试技巧", "简历模板", "职业规划",
]

# 结果公示类关键词（招聘已结束，页面是拟聘用/成绩公示，不是在招岗位）
# 注意：不要用"体检考察"这类词——正常招聘公告的流程描述里也有"体检、考察"
RESULT_NOTICE_KWS = ["拟聘用", "聘用公示", "成绩公示", "拟聘人员"]

# 公告已进入招聘后续流程（报名早已结束）——只在标题层判断，避免误伤正文流程描述
POST_STAGE_KWS = [
    "资格复审", "复审程序", "入围", "面试有关", "面试事项", "体检人员", "体检名单",
    "考察对象", "准考证", "笔试成绩", "拟聘用", "拟聘人员", "拟录用", "拟补录",
    "录用名单", "聘用公示", "成绩公示", "结果公示", "名单公告",
]

# 官方栏目直抓时，公告必须与医疗岗位相关（区级栏目常混有街道办聘员、政府雇员等非医疗岗位）
MEDICAL_HINT_KWS = [
    "卫生健康", "卫健", "医院", "医疗", "医师", "医生", "社区卫生", "疾控",
    "疾病预防控制", "卫生院", "校医", "护理", "临床", "医学", "公共卫生",
    "心电图", "体检", "全科",
]
# 正文层面的强医疗特征（用于标题不含医疗词时进一步确认，避免"体检、考察"等流程描述误判）
STRONG_MEDICAL_KWS = [
    "卫生健康局", "卫生健康委员会", "卫生健康系统", "医院", "社区卫生服务中心",
    "疾病预防控制中心", "卫生院", "校医", "执业医师", "临床医学", "公共卫生",
]
# 高特异性医疗词：命中 1 次即可认定医疗相关（用于省级/市级统考总公告这类
# "多岗位汇总"公告的召回，这类公告标题常只有"事业单位集中公开招聘"字样）
HIGH_SPECIFIC_MEDICAL_KWS = [
    "卫生健康", "社区卫生服务中心", "社区卫生服务站", "卫生服务中心",
    "疾病预防控制中心", "卫生院", "校医", "执业医师", "临床医学", "公共卫生",
    "人民医院", "中医院", "妇幼保健", "疾控中心", "医师岗位", "医疗岗",
]

# 栏目页里的非招聘政务文件/采购类公告
NON_RECRUIT_TITLE_KWS = [
    "考务服务", "比选", "采购", "中标", "成交", "招标", "询价",
    "征求意见", "意见的公告", "座谈", "培训通知", "会议通知",
]

# ── 官方栏目直抓 ─────────────────────────────────────────
# 直接抓官方招聘公告栏目列表页，解析出具体公告详情页。
# 关键：绕开搜索摘要（Tavily 抓不到政府公告正文里的报名窗口），从源头拿权威信息。
OFFICIAL_FEEDS = [
    {
        "name": "东莞市卫生健康局·编制内人员招聘",
        "url": "https://dghb.dg.gov.cn/ztpd/gkzp/zpgg/",
        "city": "东莞",
    },
    {
        "name": "东莞市卫生健康局·编制外人员招聘",
        "url": "https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/",
        "city": "东莞",
    },
    {
        "name": "广州市卫生健康委员会·通知公告",
        "url": "http://wjw.gz.gov.cn/xxgk/tzgg/",
        "city": "广州",
    },
    {
        "name": "广州市海珠区人社局·考试招聘",
        "url": "https://www.haizhu.gov.cn/gzjg/qzf/hzqrsj/kszp",
        "city": "广州",
    },
    {
        "name": "广州市白云区·招考信息",
        "url": "https://www.by.gov.cn/zwgk/zdlyxxgkzl/jycyxxgkzl/zpxx/",
        "city": "广州",
    },
    {
        "name": "广州市番禺区·招考信息",
        "url": "http://www.panyu.gov.cn/zwgk/rsgk/zkxx/index.html",
        "city": "广州",
    },
    {
        "name": "广州市花都区卫生健康局·公告栏",
        "url": "https://www.huadu.gov.cn/gzjg/qzfgzbm/qwsjkj/ggl/",
        "city": "广州",
    },
    # ── 2026-10-12 扩充：东莞人社/市政府 + 广东省人社厅 + 广州其余各区 ──
    # 带 prefilter_medical 标记的为"综合类招考栏目"（混有街道聘员/教师/环卫等），
    # 先做标题层医疗预判再抓详情页，节省大量无效请求。
    {
        "name": "东莞市人力资源和社会保障局·编制外人员招聘",
        "url": "https://dghrss.dg.gov.cn/xwzx/gsgg/gkzp/bzwryzp/",
        "city": "东莞",
        "prefilter_medical": True,
    },
    {
        "name": "东莞市人民政府·招考信息",
        "url": "https://www.dg.gov.cn/zwgk/zfgb/zkxx/",
        "city": "东莞",
        "prefilter_medical": True,
    },
    {
        "name": "广东省人力资源和社会保障厅·事业单位招聘公告",
        "url": "https://hrss.gd.gov.cn/zwgk/sydwzp/zpgg/",
        "city": "广州",
        "prefilter_medical": True,
    },
    {
        "name": "广州市荔湾区·招聘信息",
        "url": "http://www.lw.gov.cn/ywdt/lwzp/index.html",
        "city": "广州",
        "prefilter_medical": True,
    },
    {
        "name": "广州市黄埔区·招聘公告",
        "url": "http://www.hp.gov.cn/xwzx/tzgg/zpgg/",
        "city": "广州",
        "prefilter_medical": True,
    },
    {
        "name": "广州市增城区·单位招聘",
        "url": "http://www.zc.gov.cn/gk/rsgz/dwzp/",
        "city": "广州",
        "prefilter_medical": True,
    },
    {
        "name": "广州市越秀区·招聘公告",
        "url": "https://www.yuexiu.gov.cn/zwgk/rsxx/gkzkzp/zpgg/",
        "city": "广州",
        "prefilter_medical": True,
    },
    # ── 2026-10-12 二轮扩充：补东莞编内 + 广州卫健委人事信息栏 + 从化/南沙 ──
    {
        "name": "东莞市人力资源和社会保障局·编制内人员招聘",
        "url": "https://dghrss.dg.gov.cn/xwzx/gsgg/gkzp/zpgg/",
        "city": "东莞",
        "prefilter_medical": True,
    },
    {
        "name": "广州市卫生健康委员会·人事信息",
        "url": "http://wjw.gz.gov.cn/xxgk/rsxx/",
        "city": "广州",
    },
    {
        "name": "广州市从化区·公告公示",
        "url": "https://www.conghua.gov.cn/zwgk/gggs/",
        "city": "广州",
        "prefilter_medical": True,
    },
    {
        "name": "广州市南沙区·通知公告",
        "url": "https://www.gzns.gov.cn/zwgk/tzgg/",
        "city": "广州",
        "prefilter_medical": True,
    },
]

# 综合类招考栏目里，标题必须命中这些词才值得抓详情页
# （医疗岗位公告标题几乎必含"医院/卫生健康/事业单位"等，反之街道聘员/环卫/教师可安全跳过）
OFFICIAL_PREFILTER_KWS = [
    "医院", "医疗", "医师", "医生", "卫生健康", "卫健", "卫生", "社区卫生",
    "疾控", "疾病预防", "卫生院", "校医", "公共卫生", "临床", "医学", "体检",
    "心电图", "事业单位",
]

# 列表页中属于"具体公告详情页"的链接特征（用于剔除栏目页/首页链接）
_DETAIL_URL_KWS = ("/content/post_", "/content/", "/info/", "/detail/")

# 陈旧公告阈值：无未来截止日期 + 发布超过该天数 -> 视为过期剔除
STALE_DAYS = 45

# 初始种子数据（当 jobs.json 不存在或 Tavily 失败时仍有内容展示）
# 注意：原东莞市妇幼保健院 FY007/FY010/FY019 三条种子已于 2026-10-12 移除。
# 该批次原始公告写"报名至 2026-11-30"，但 2026-05-22《关于报名截止时间修改的公告》
# 把截止日提前到了 5 月 31 日（见 DEADLINE_OVERRIDES），实际早已截止。
SEED_JOBS = [
    {
        "title": "2026年广州市海珠区卫生健康系统公开招聘事业单位工作人员公告",
        "hospital": "广州市海珠区人社局",
        "city": "广州",
        "category": "卫健委",
        "url": "https://www.haizhu.gov.cn/gzjg/qzf/hzqrsj/kszp/content/post_11025879.html",
        "source": "广州市海珠区人社局·考试招聘",
        "publish_date": "2026-09-29",
        "deadline": "2026-10-15",
        "has_bianzhi": True,
        "reliability": "官方",
        "description": "面向社会公开招聘 99 名事业编制工作人员，含区属医疗卫生机构及社区卫生服务中心岗位。",
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

def _norm_url(u):
    """URL 规范化：去协议/www/fragment/query/尾斜杠与尾部杂字符。

    用于黑名单比对与去重——同一页面 http/https、带不带 www 必须视为同一条，
    否则会像 2026-09 那样出现「拉黑后换协议又复活」的问题。
    """
    u = (u or "").strip().lower()
    u = u.split("#")[0].split("?")[0]
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/").rstrip(":, ")


# 人工确认已下线/失效/过期的 URL（规范化后比对，忽略 http/https、www、尾斜杠差异）
MANUAL_DEAD_URLS = {
    _norm_url(u) for u in [
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
        # 东莞市卫生健康局官网首页畸形URL（末尾带冒号），请求404（2026-09-09 用户反馈打不开 + 实测404）
        "http://dghb.dg.gov.cn/:",
        # 2026年广州市南沙区卫健局公开招聘下属事业单位工作人员公告，报名期2026-08-18至08-24已截止（2026-09-09 核查正文确认）
        "http://www.gzns.gov.cn/zwgk/tzgg/content/post_10962793.html",
        # 东莞市公立医院2026年公开招聘医学类高校优秀应届毕业生公告（百万英才汇南粤批次），3月报名已截止（2026-09-09 核查确认）
        "https://dghb.dg.gov.cn/ztpd/gkzp/zpgg/content/post_4511514.html",
        # 2026年广州市南沙区卫健局急需专业人才引进，报名期2026-09-01至09-20已截止（2026-09-21 核查正文确认）
        "http://www.gzns.gov.cn/zwgk/tzgg/content/post_10980178.html",
        # 百万英才汇南粤|东莞市樟木头医院2026年编外人员招聘，报名2026-04-13至04-26已截止（2026-09-21 核查正文确认）
        "http://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4522897.html",
        # 广州市白云区卫健系统2026年公开招聘（第一批）【另一路径页面】，7月发布报名已截止（2026-09-21 核查确认）
        "https://www.by.gov.cn/ywdt/tzgg/content/post_10902497.html",
        # 东莞市南城社区卫生服务中心（康强医疗人才网聚合页，所列岗位全部显示"已结束"）（2026-09-21 核查确认）
        "https://3g.kq36.com/25/c-7062",
        # 2026年广州市增城区卫健局下属事业单位公开招聘——页面无报名窗口，批次早已结束（2026-10-12 复核确认）
        "http://www.zc.gov.cn/gk/rsgz/dwzp/content/post_10749247.html",
        # 松山湖社区卫生服务中心"医联体"下属单位专栏页——栏目介绍，非招聘公告（2026-10-12 核查确认）
        "http://ssl.dg.gov.cn/sslchs/ylt/content/post_3963745.html",
    ]
}


# 招聘语义关键词：标题/摘要必须含其一，否则视为栏目页/机构介绍页（如"医联体_XX社区卫生服务中心"）
RECRUIT_SEMANTIC_KWS = ["招聘", "招考", "招录", "招人", "选聘", "选调", "引进", "招募", "补录", "纳编"]


# 报名截止日期的**官方后续修正**（规范化 URL -> 实际截止日）
# 背景：政府部门常在批次公告发布数周后再发一条"报名截止时间修改的公告"，
# 原始公告正文里的截止日随之失效。若不按修正值覆盖，这类批次会挂着错误的
# "远期截止日"长期滞留在列表里（2026-10 发现的妇幼保健院案例，虚挂 4 个月）。
# 新增修正值时，请一并核对来源公告 URL 与核查日期。
DEADLINE_OVERRIDES = {
    # 来源：2026-05-22《关于报名截止时间修改的公告》
    # http://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4541529.html
    # "统一将以上 6 家医院纳入岗位管理编外人员招聘报名截止时间修改为 2026 年 5 月 31 日"
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4494129.html"): ("2026-05-31", "东莞市妇幼保健院"),
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4528842.html"): ("2026-05-31", "东莞市人民医院"),
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4525339.html"): ("2026-05-31", "东莞市中西医结合医院"),
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4507557.html"): ("2026-05-31", "滨海湾中心医院"),
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4507556.html"): ("2026-05-31", "东南部中心医院"),
    _norm_url("https://dghb.dg.gov.cn/ztpd/gkzp/bzwryzp/content/post_4507553.html"): ("2026-05-31", "东部中心医院"),
}


def _apply_deadline_overrides(jobs):
    """用官方后续修正公告的截止日期覆盖公告原始值（必须早于 _drop_expired 执行）。"""
    for j in jobs:
        hit = DEADLINE_OVERRIDES.get(_norm_url(j.get("url", "")))
        if not hit:
            continue
        fixed, who = hit
        if j.get("deadline") != fixed:
            print(f"[ddl-fix] {who}: 原截止 {j.get('deadline') or '无'} -> 修正为 {fixed}")
            j["deadline"] = fixed
    return jobs


def check_url_alive(url):
    """检测链接是否存活。仅 404/410 或明确的失效文案才判 dead。"""
    if not url or not str(url).startswith("http"):
        return "dead"
    base_url = str(url).split("#")[0]
    if _norm_url(base_url) in MANUAL_DEAD_URLS:
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


_TAVILY_QUOTA_DEAD = False   # 一旦命中配额耗尽(432)，后续查询直接短路，不再空打请求


def _tavily_search_one(query, api_key, max_results=8, days=60):
    """调用 Tavily API 搜索一次。配额耗尽时快速失败并置全局标记。"""
    global _TAVILY_QUOTA_DEAD
    if _TAVILY_QUOTA_DEAD:
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
            timeout=30,
        )
        if r.status_code == 432:
            _TAVILY_QUOTA_DEAD = True
            print("[tavily] ⚠ 配额已用尽（HTTP 432 / exceeds your plan's set usage limit），"
                  "本次跳过全部搜索，仅使用官方栏目直抓结果")
            return None
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

    # 报名窗口：公告常写"报名时间为 X月X日至 X月X日"。
    # 取窗口"末端"作为截止日，并优先于 parser 的日期猜测
    # （parser 可能把报名首日误当截止日，导致在招岗位被当成已截止剔除）。
    if content:
        m = re.search(
            r"报名(?:时间|期)?[为是]?[^。]{0,90}?[至到—\-]\s*(?:20\d{2}年?)?(\d{1,2})月(\d{1,2})日",
            content,
        )
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                item["deadline"] = f"{datetime.now().year}-{month:02d}-{day:02d}"
                print(f"[deadline] 报名窗口末端: {item.get('title','')[:24]} -> {item['deadline']}")

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
    """剔除城市不在 广州/东莞 范围内的岗位（含标题中出现外地城市/省份但 city 字段误标的情况）。"""
    other_cities = [
        # 省外主要城市
        "北京", "上海", "深圳", "武汉", "长沙", "成都", "重庆", "杭州",
        "南京", "西安", "郑州", "福州", "昆明", "贵阳", "南昌", "合肥",
        "天津", "苏州", "青岛", "济南", "厦门", "宁波", "温州", "无锡",
        "常州", "徐州", "石家庄", "太原", "沈阳", "大连", "长春", "哈尔滨",
        "南宁", "海口", "三亚", "兰州", "银川", "西宁", "乌鲁木齐", "呼和浩特",
        "拉萨", "绵阳", "襄阳", "宜昌",
        # 省/自治区名（标题出现即外地；广东省本身不在其列）
        "四川", "湖北", "湖南", "浙江", "江苏", "安徽", "福建", "河南",
        "河北", "陕西", "山西", "辽宁", "吉林", "黑龙江", "江西", "广西",
        "云南", "贵州", "甘肃", "宁夏", "新疆", "西藏", "内蒙古", "青海",
        "海南",
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
    # 归一化 URL：去 fragment、去尾部杂字符（Tavily 偶发在 URL 尾带 ':'）
    url = (j.get("url") or "").lower().split("#")[0].strip().rstrip(":, ")
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
    # 栏目/列表页：URL 以目录或 index 页结尾（如 wjw.gz.gov.cn/xxgk/rsxx/、.../zpgg/index.html）
    # 只按"结尾形态"判定，不按"是否含详情特征"反推 —— 后者会误杀 /t20261010_12345.html
    # 这类没有 post_/content 特征的具体公告
    if url.endswith("/") or re.search(r"/index\.(?:s?html?|jsp|php|aspx)$", url):
        return "栏目页URL"
    if any(p in title for p in AGG_TITLE_PATTERNS):
        return "聚合页标题"
    if title in GENERIC_TITLES:
        return "泛化标题"
    if any(k in title for k in NON_JOB_TITLE_KWS):
        return "非招聘岗位"
    # 采购/考务/征求意见等政务文件，不是招聘岗位（如"公开招聘考务服务项目比选结果的公示"）
    if any(k in title for k in NON_RECRUIT_TITLE_KWS):
        return "政务采购类"
    # 教师招聘等非医疗岗位（校医/医疗卫生类公告不受影响）
    if "教师" in title and not any(k in title for k in ("校医", "医师", "医疗", "卫生")):
        return "非医疗岗位"
    # 招聘已进入后续流程的公告（复审/面试/体检/名单），报名早已结束
    if any(k in title for k in POST_STAGE_KWS):
        return "招聘后续流程公告"
    # 招聘语义白名单：标题+摘要里没有任何招聘动作词的，几乎都是栏目页/介绍页
    # （如"医联体_东莞松山湖社区卫生服务中心_管委会"这类下属单位专栏页）
    blob = title + " " + (j.get("description") or "")[:200]
    if not any(k in blob for k in RECRUIT_SEMANTIC_KWS):
        return "无招聘语义"
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


def _host_of(url):
    """取 URL 的主机名（规范化后）。"""
    return _norm_url(url).split("/")[0]


def _is_thirdparty(url):
    host = _host_of(url)
    return any(host == h or host.endswith("." + h) for h in THIRDPARTY_HOSTS)


def _drop_undated_thirdparty(jobs):
    """剔除第三方人才网的无日期条目：发布/截止日期都抓不到时无法验证时效，一律不收。"""
    kept = []
    for j in jobs:
        if _is_thirdparty(j.get("url", "")) and not j.get("publish_date") and not j.get("deadline"):
            print(f"[no-date] 剔除无日期第三方条目: {(j.get('title') or '')[:32]} -> {_host_of(j.get('url', ''))}")
            continue
        kept.append(j)
    return kept


_DATE_SEP = re.compile(r"(20\d{2})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})")


def _page_reg_deadline(url):
    """抓页面正文，从"报名…"段落里取最晚日期作为报名截止日。失败/无匹配返回 None。"""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=18,
            verify=False,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return None
        text = re.sub(r"<[^>]+>", " ", r.text or "")
        text = re.sub(r"\s+", "", text)  # 政府站点日期常被标签/空格拆开，去空白后再匹配
        best = None
        for m in re.finditer(r"报名[^。；]{0,160}", text):
            for y, mo, d in _DATE_SEP.findall(m.group(0)):
                try:
                    dt = datetime(int(y), int(mo), int(d)).date()
                except Exception:
                    continue
                if best is None or dt > best:
                    best = dt
        return best
    except Exception:
        return None


def _needs_reg_check(j):
    """仅对"政府官网公告页 + 无未来截止日期"的条目做正文核查，控制请求量。"""
    url = j.get("url") or ""
    if "gov.cn" not in _host_of(url):
        return False
    ddl = j.get("deadline")
    if ddl:
        try:
            if datetime.strptime(str(ddl)[:10], "%Y-%m-%d").date() >= datetime.now().date():
                return False
        except Exception:
            pass
    return True


def _drop_deadline_passed(jobs):
    """正文报名窗口核查：公告正文写明报名期且已结束的，直接剔除。

    这类公告的截止日期往往藏在正文（Tavily 摘要抓不到），仅靠 deadline 字段
    会漏网（如南沙 9-20 截止、樟木头 4 月截止的公告）。
    """
    targets = [j for j in jobs if _needs_reg_check(j)]
    if not targets:
        return jobs
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda j: _page_reg_deadline(j.get("url", "")), targets))
    today = datetime.now().date()
    closed = {}
    for j, dl in zip(targets, results):
        if dl and dl < today:
            closed[_norm_url(j.get("url", ""))] = dl
    kept = []
    for j in jobs:
        dl = closed.get(_norm_url(j.get("url", "")))
        if dl:
            print(f"[reg-deadline] 剔除报名已截止({dl}): {(j.get('title') or '')[:32]}")
            continue
        kept.append(j)
    return kept


_ANCHOR_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _fetch_html(url, timeout=20):
    """抓取页面 HTML，自动尝试 utf-8 / gbk 解码（政府站点多为 GBK）。"""
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return None
        raw = r.content
        for enc in ("utf-8", "gbk", "gb18030"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", "ignore")
    except Exception:
        return None


def _list_feed_announcements(feed, limit=12):
    """抓官方栏目列表页，解析出具体公告详情页的 (url, title) 列表。"""
    html = _fetch_html(feed["url"])
    if not html:
        print(f"[feed] 列表页无法访问: {feed['name']}")
        return []
    base = feed["url"]
    out, seen = [], set()
    for href, inner in _ANCHOR_RE.findall(html):
        title = re.sub(r"\s+", "", _TAG_RE.sub("", inner)).strip()
        if len(title) < 10:
            continue
        if not any(k in title for k in ("招聘", "公告", "招考", "引进")):
            continue
        full = urljoin(base, href.strip())
        # 只保留具体公告详情页，剔除栏目页/首页链接
        if not any(k in full for k in _DETAIL_URL_KWS):
            continue
        if not full.startswith("http") or full in seen:
            continue
        seen.add(full)
        out.append((full, title))
        if len(out) >= limit:
            break
    return out


def _feed_announcement_ok(title):
    """标题层快速排除：非招聘政务文件、后续流程公告、采购文件、非医疗岗位。"""
    # 必须是招聘类公告（栏目页里混有"职权调整""实施意见"等纯政务公告）
    if not any(k in title for k in ("招聘", "招考", "招录", "选聘", "引进")):
        return "非招聘政务公告"
    if any(k in title for k in POST_STAGE_KWS):
        return "招聘后续流程公告"
    if any(k in title for k in RESULT_NOTICE_KWS):
        return "结果公示"
    if any(k in title for k in NON_RECRUIT_TITLE_KWS):
        return "政务采购类"
    if any(k in title for k in NON_JOB_TITLE_KWS):
        return "非招聘岗位"
    if "教师" in title and not any(k in title for k in ("校医", "医师", "医疗", "卫生")):
        return "非医疗岗位"
    return None


def _parse_official_announcement(url, title, feed):
    """把官方公告详情页解析成岗位条目；不属于在招岗位时返回 None。"""
    why = _feed_announcement_ok(title)
    if why:
        return None
    # 综合类招考栏目：标题层先做医疗预判，避免为街道聘员/环卫/教师等白抓详情页
    if feed.get("prefilter_medical") and not any(k in title for k in OFFICIAL_PREFILTER_KWS):
        return None
    html = _fetch_html(url)
    if not html:
        return None

    # 先去 <script>/<style> 整块，避免页内脚本污染摘要
    body_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    raw = re.sub(r"\s+", " ", _TAG_RE.sub(" ", body_html))
    compact = re.sub(r"\s+", "", raw)

    # 先提取正文摘要（跳过导航/页脚），长版用于相关性判定，短版用于展示描述
    snippet_long = _extract_body_snippet(raw, title, width=2500)
    snippet = snippet_long[:420]

    # 正文里也出现公示类表述的，同样剔除
    if any(k in compact[:3000] for k in RESULT_NOTICE_KWS):
        return None

    # 医疗相关性：区级招考栏目常混有街道办聘员、政府雇员等非医疗岗位。
    # 只判定标题 + 正文（全页文本含导航链接，会把非医疗公告误判为医疗类）。
    # 省级/市级统考总公告标题往往只有"事业单位集中公开招聘"，需靠正文召回。
    if not any(k in title for k in MEDICAL_HINT_KWS):
        if any(k in snippet_long for k in HIGH_SPECIFIC_MEDICAL_KWS):
            pass                                  # 高特异性医疗词命中，认定医疗类
        elif sum(snippet_long.count(k) for k in STRONG_MEDICAL_KWS) >= 2:
            pass                                  # 普通医疗词密集出现（多岗位汇总公告）
        else:
            print(f"[feed] 非医疗岗位，跳过: {title[:44]}")
            return None

    # 报名截止：正文"报名…"段落里的最晚日期
    deadline = _extract_reg_deadline_from_text(compact)

    # 发布日期
    pub = None
    m = re.search(
        r"(?:发布日期|发布时间|发文日期|时间)[：:\s]*(20\d{2})[年./\-](\d{1,2})[年./\-](\d{1,2})",
        compact,
    )
    if m:
        try:
            pub = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except Exception:
            pub = None

    # 时效判断：必须能确认"未来仍可报名"，否则不收（避免推荐过期岗位）
    today = datetime.now().date()
    if deadline:
        if deadline < today:
            print(f"[feed] 报名已截止({deadline}): {title[:40]}")
            return None
    elif pub:
        try:
            p = datetime.strptime(pub, "%Y-%m-%d").date()
            if (today - p).days > STALE_DAYS:
                print(f"[feed] 陈旧公告(发布于{pub}): {title[:40]}")
                return None
        except Exception:
            return None
    else:
        print(f"[feed] 无法确认时效，跳过: {title[:40]}")
        return None

    # 类别判定（用标题 + 正文摘要，避免导航文字干扰）
    cat = parser.categorize(title + " " + snippet)
    if cat == "其他":
        if any(k in title + snippet for k in ("卫生健康", "卫健", "医院", "医疗", "卫生")):
            cat = "卫健委"       # 卫健系统统一招聘公告（含多家医院多岗位）
        else:
            return None
    if cat not in ("体检科", "心电图", "社区医师", "校医", "心血管内科", "AI医疗", "卫健委", "疾控中心"):
        return None

    desc = snippet or f"来源：{feed['name']}"

    # 医院名：公告标题里常含"XX医院/XX社区卫生服务中心"
    hm = re.search(r"([\u4e00-\u9fa5]{2,14}(?:医院|社区卫生服务中心|疾控中心|卫生服务中心))", title)
    hospital = hm.group(1) if hm else feed["name"].split("·")[0]

    return {
        "title": title[:80],
        "hospital": hospital,
        "city": feed["city"],
        "category": cat,
        "url": url,
        "source": feed["name"],
        "publish_date": pub or "",
        "deadline": deadline.strftime("%Y-%m-%d") if deadline else "",
        "has_bianzhi": parser.detect_bianzhi(title + " " + compact[:4000]),
        "reliability": "官方",
        "description": desc[:400],
        "status": "active",
    }


# 政府网页导航/页脚特征词（摘要里出现即说明截到了导航区，需跳过）
_NAV_JUNK_KWS = [
    "无障碍", "长者助手", "网站支持IPv6", "千人千页", "搜索位置", "我的收藏",
    "打印页面", "关闭页面", "网站地图", "要闻动态", "政务服务", "互动交流",
    "统一登录", "网站标识码", "主办单位", "版权", "联系我们",
]


def _clean_snippet(s):
    """清理正文片段里的脚本残留、样式符号。"""
    s = s.replace("&nbsp;", " ")
    s = re.sub(r"\$\([^)]{0,60}\)[\s\S]{0,80}", " ", s)                # jQuery 残留
    s = re.sub(r"(?:document|window|function|var|return)\b[\s\S]{0,60}?[;}]", " ", s)
    s = re.sub(r"[{}<>]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ·|-—_")


def _extract_body_snippet(raw, title, width=420):
    """从公告页正文中截取可读摘要（跳过导航栏/页脚/脚本残留）。"""
    key = re.sub(r"\s+", "", title)[:12]
    starts = [m.start() + len(key) for m in re.finditer(re.escape(key), raw)] if key else []
    for start in starts:
        seg = _clean_snippet(raw[start: start + width * 2])
        head = seg[:300]
        # 导航区/页脚：含导航特征词，或没有招聘语义
        if any(k in head for k in _NAV_JUNK_KWS):
            continue
        if any(k in head for k in ("招聘", "报名", "岗位", "引进", "招考")):
            # 跳过"发布日期/来源/浏览量/分享到"这类页头元信息，从正文首句开始
            m2 = re.search(r"(根据|现将|为[^。]{0,24}(?:招聘|充实|加强|满足|优化))", seg[:220])
            if m2 and m2.start() > 0:
                seg = seg[m2.start():]
            return seg[:width]
    m = re.search(r"(根据[^。]{0,80}?招聘|为[^。]{0,60}?招聘|现将[^。]{0,80})", raw)
    if m:
        return _clean_snippet(raw[m.start(): m.start() + width * 2])[:width]
    # 兜底：全文里第一段不含导航特征词的内容
    for part in re.split(r"\s{2,}", raw):
        seg = _clean_snippet(part)
        if len(seg) > 60 and not any(k in seg[:200] for k in _NAV_JUNK_KWS):
            return seg[:width]
    return _clean_snippet(raw[:width * 2])[:width]


def _extract_reg_deadline_from_text(compact):
    """从已去空白的正文里提取"报名…"段落中的最晚日期，作为报名截止日。"""
    best = None
    for m in re.finditer(r"报名[^。；]{0,160}", compact or ""):
        for y, mo, d in _DATE_SEP.findall(m.group(0)):
            try:
                dt = datetime(int(y), int(mo), int(d)).date()
            except Exception:
                continue
            if best is None or dt > best:
                best = dt
    return best


def fetch_official_jobs(feeds=None):
    """官方栏目直抓主入口：返回解析好的岗位条目列表。"""
    feeds = feeds or OFFICIAL_FEEDS
    out = []
    for feed in feeds:
        anns = _list_feed_announcements(feed)
        print(f"[feed] {feed['name']}: 列表页解析出 {len(anns)} 条公告")
        for url, title in anns:
            try:
                item = _parse_official_announcement(url, title, feed)
            except Exception as e:
                print(f"[feed] 解析异常 {url[:60]}: {e}")
                continue
            if item:
                out.append(item)
                print(f"[feed] ✓ {item['city']} | {item['title'][:44]} | ddl={item['deadline'] or '无'}")
            time.sleep(0.2)
    return out


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
            # 第三方人才网的无日期条目：无法验证时效，不收
            if _is_thirdparty(url) and not item.get("publish_date") and not item.get("deadline"):
                print(f"[no-date] 丢弃无日期第三方结果: {item.get('title', '')[:30]} -> {url[:70]}")
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


def _dedupe_by_title(jobs, official_urls):
    """同一公告常同时抓到官方页与第三方转载页（标题相同、URL 不同），只保留一条。

    优先保留官方直抓来源，其次保留能确认时效（有截止日）的那条。
    """
    slots = []
    pos_of = {}
    for j in jobs:
        key = re.sub(r"\s+", "", (j.get("title") or ""))[:45] or None
        if key is None:
            slots.append(j)
            continue
        pos = pos_of.get(key)
        if pos is None:
            pos_of[key] = len(slots)
            slots.append(j)
            continue
        prev = slots[pos]
        prev_off = prev.get("url") in official_urls
        new_off = j.get("url") in official_urls
        better = (new_off and not prev_off) or (
            new_off == prev_off and j.get("deadline") and not prev.get("deadline")
        )
        if better:
            slots[pos] = j
            print(f"[dedupe] 同公告保留更权威版本: {key[:38]}")
        else:
            print(f"[dedupe] 同公告去重: {key[:38]}")
    return slots


def build_jobs_data(tavily_items=None, official_items=None):
    """构建最终写入 jobs.json 的数据结构。"""
    existing = load_existing_jobs()
    # 以种子数据打底
    seed_map = {j["url"]: j for j in SEED_JOBS}
    existing_map = {j["url"]: j for j in existing if j.get("url")}

    # 合并优先级：官方直抓 > Tavily 新数据 > 现有 > 种子
    # 官方直抓来自公告详情页正文核查，权威性和时效准确性都高于搜索摘要，
    # 同一 URL 时以官方版本为准（否则搜索摘要里的错误截止日会覆盖掉正确值）。
    final_map = dict(seed_map)
    final_map.update(existing_map)
    for j in tavily_items or []:
        if j.get("url"):
            final_map[j["url"]] = j
    for j in official_items or []:
        if j.get("url"):
            final_map[j["url"]] = j

    jobs = list(final_map.values())
    # 去重：同一公告的官方页与第三方转载页只留一条
    jobs = _dedupe_by_title(jobs, {j.get("url") for j in (official_items or [])})
    # 清理链：聚合页 -> 外地 -> 结果公示 -> 已截止/陈旧 -> 无日期第三方 -> 正文报名窗口核查 -> 死链复检
    jobs = _drop_agg_jobs(jobs)
    jobs = _drop_wrong_city(jobs)
    jobs = _drop_result_notices(jobs)
    jobs = _apply_deadline_overrides(jobs)
    jobs = _drop_expired(jobs)
    jobs = _drop_stale_jobs(jobs)
    jobs = _drop_undated_thirdparty(jobs)
    jobs = _drop_deadline_passed(jobs)
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

    # 1) 官方栏目直抓（权威、时效可核查，不受搜索摘要影响）
    official_items = fetch_official_jobs()

    # 2) Tavily 补充搜索（覆盖非栏目化的零散公告）
    new_items = fetch_jobs(api_key=api_key)

    data = build_jobs_data(new_items, official_items)

    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[done] total={data['total']} updated_at={data['updated_at']}")
    active = sum(1 for j in data["jobs"] if j.get("status") == "active")
    bianzhi = sum(1 for j in data["jobs"] if j.get("has_bianzhi"))
    print(f"       active={active} bianzhi={bianzhi}")


if __name__ == "__main__":
    main()
