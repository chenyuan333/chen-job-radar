"""
SQLite 数据库层 - 岗位雷达小程序
"""
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    hospital TEXT,
    city TEXT,
    category TEXT NOT NULL,
    salary TEXT,
    description TEXT,
    url TEXT NOT NULL,
    source TEXT,
    publish_date TEXT,
    deadline TEXT,
    has_bianzhi INTEGER DEFAULT 0,
    reliability TEXT DEFAULT '待审',
    status TEXT DEFAULT 'active',
    user_status TEXT DEFAULT 'new',
    crawled_at TEXT,
    added_at TEXT NOT NULL,
    notes TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_city ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_status);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS crawl_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at TEXT NOT NULL,
    keyword TEXT,
    found_count INTEGER DEFAULT 0,
    added_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok',
    error TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# 初始化默认设置
DEFAULT_SETTINGS = {
    "default_keywords": "东莞 体检科医师\n东莞 心电图医师\n东莞 全科医师\n东莞 校医\n东莞 疾控\n广州 体检科医师\n广州 心电图医师\n广州 全科医师\n广州 校医",
    "default_city": "东莞,广州",
    "default_categories": '["体检科","心电图","社区医师","校医","卫健委","疾控中心","AI医疗","其他"]',
    "schedule_enabled": "false",
    "last_crawl_at": "",
}

# 岗位雷达仅服务陈医生关注的东莞、广州两地
ALLOWED_CITIES = ["东莞", "广州"]

# 搜索同义词组：用户输入其中任意一个词，自动扩展匹配整组相关词
SEARCH_SYNONYM_GROUPS = [
    ["健康管理", "健康体检", "健康管理中心", "健康管理科", "健康体检中心", "体检中心", "体检"],
    ["心血管", "心内科", "心脏"],
    ["心电图", "心电"],
    ["社区", "社卫", "全科"],
    ["校医", "学校医师", "校园医生"],
    ["疾控", "疾病预防控制", "卫生监督"],
]


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
        "title": "心血管内科医生 ZXY26104",
        "hospital": "东莞市中西医结合医院",
        "city": "东莞",
        "category": "心电图",
        "url": "https://dghb.dg.gov.cn/gkmlpt/content/4/4525/post_4525339.html#ZXY26104",
        "source": "官方公告",
        "publish_date": "2026-04-10",
        "deadline": "2026-08-31",
        "has_bianzhi": False,
        "reliability": "官方",
        "description": "心血管内科方向硕士，35周岁以下，需完成规培并取得执业医师资格证。",
    },
    {
        "title": "心血管内科骨干医生 RY002",
        "hospital": "南方医科大学第十附属医院（东莞市人民医院）",
        "city": "东莞",
        "category": "心电图",
        "url": "https://dghb.dg.gov.cn/gkmlpt/content/4/4528/post_4528842.html#RY002",
        "source": "官方公告",
        "publish_date": "2026-04-17",
        "deadline": "2026-08-31",
        "has_bianzhi": False,
        "reliability": "官方",
        "description": "内科学博士，医师及以上职称，35周岁以下。三甲医院平台。",
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
    {
        "title": "健康体检中心医师",
        "hospital": "广东医科大学附属东莞松山湖中心医院",
        "city": "东莞",
        "category": "体检科",
        "url": "https://www.jobmd.cn/work/1390912.htm",
        "source": "丁香人才网",
        "publish_date": "",
        "deadline": "",
        "has_bianzhi": False,
        "reliability": "第三方",
        "description": "本科及以上，内科学/外科学/临床医学。初级医师需完成规培，具有三甲医院临床专科工作经历和科教研能力优先。五险一金、工作餐、节日福利。",
    },
    {
        "title": "健康管理中心医师（041）",
        "hospital": "东莞市松山湖中心医院",
        "city": "东莞",
        "category": "体检科",
        "url": "https://www.fenbi.com/page/positions/11/192796?department=%E4%B8%9C%E8%8E%9E%E5%B8%82%E6%9D%BE%E5%B1%B1%E6%B9%96%E4%B8%AD%E5%BF%83%E5%8C%BB%E9%99%A2&page=5",
        "source": "粉笔教育职位表/东莞市公立医院2026年招聘",
        "publish_date": "2026-03-13",
        "deadline": "2026-03-31",
        "has_bianzhi": True,
        "reliability": "官方",
        "status": "expired",
        "description": "东莞市公立医院2026年公开招聘医学类高校优秀应届毕业生岗位。岗位代码041，招录1人，硕士研究生及以上，公共卫生与预防医学/公共卫生。报名已结束。",
    },
]


def init_db():
    """初始化数据库（启动时调用）"""
    is_new = not os.path.exists(DB_PATH)
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (k, v),
            )
        # 首次创建数据库时，预置几条已知高质量岗位，避免页面空白
        if is_new:
            existing = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
            if existing == 0:
                for job in SEED_JOBS:
                    conn.execute(
                        """
                        INSERT INTO jobs(
                          title, hospital, city, category, salary, description, url,
                          source, publish_date, deadline, has_bianzhi, reliability,
                          status, user_status, crawled_at, added_at, notes
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            job["title"].strip(),
                            (job.get("hospital") or "").strip() or None,
                            (job.get("city") or "").strip() or None,
                            job.get("category", "其他").strip(),
                            (job.get("salary") or "").strip() or None,
                            (job.get("description") or "").strip() or None,
                            job["url"].strip(),
                            (job.get("source") or "").strip() or None,
                            (job.get("publish_date") or "").strip() or None,
                            (job.get("deadline") or "").strip() or None,
                            1 if job.get("has_bianzhi") else 0,
                            (job.get("reliability") or "待审").strip(),
                            job.get("status") or "active",
                            job.get("user_status") or "new",
                            now_iso(),
                            now_iso(),
                            (job.get("notes") or "").strip() or None,
                        ),
                    )
    return is_new


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso():
    return datetime.now().strftime("%Y-%m-%d")


# ------- 岗位 CRUD -------

def add_job(data):
    """
    新增岗位。data 字段：
      title, hospital, city, category, salary, description, url,
      source, publish_date, deadline, has_bianzhi (bool), reliability, notes
    返回: ('inserted', job_id) 或 ('duplicate', existing_id) 或 ('invalid', error)
    """
    url = (data.get("url") or "").strip()
    if not url:
        return ("invalid", "url 不能为空")
    if not data.get("title"):
        return ("invalid", "title 不能为空")
    if not data.get("category"):
        return ("invalid", "category 不能为空")

    with get_db() as conn:
        # 查重（URL）
        existing = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()
        if existing:
            return ("duplicate", existing["id"])

        cur = conn.execute(
            """
            INSERT INTO jobs(
              title, hospital, city, category, salary, description, url,
              source, publish_date, deadline, has_bianzhi, reliability,
              status, user_status, crawled_at, added_at, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data["title"].strip(),
                (data.get("hospital") or "").strip() or None,
                (data.get("city") or "").strip() or None,
                data["category"].strip(),
                (data.get("salary") or "").strip() or None,
                (data.get("description") or "").strip() or None,
                url,
                (data.get("source") or "").strip() or None,
                (data.get("publish_date") or "").strip() or None,
                (data.get("deadline") or "").strip() or None,
                1 if data.get("has_bianzhi") else 0,
                (data.get("reliability") or "待审").strip(),
                data.get("status") or "active",
                data.get("user_status") or "new",
                data.get("crawled_at") or now_iso(),
                now_iso(),
                (data.get("notes") or "").strip() or None,
            ),
        )
        return ("inserted", cur.lastrowid)


def add_jobs_bulk(items):
    """批量入库（抓取用），返回 (inserted, duplicate, invalid) 数量"""
    inserted = duplicate = invalid = 0
    errors = []
    for it in items:
        result = add_job(it)
        if result[0] == "inserted":
            inserted += 1
        elif result[0] == "duplicate":
            duplicate += 1
        else:
            invalid += 1
            errors.append(result[1])
    return {"inserted": inserted, "duplicate": duplicate, "invalid": invalid, "errors": errors[:5]}


def expand_search_keywords(q):
    """把搜索词扩展为同义词列表，支持模糊匹配"""
    if not q:
        return []
    q = q.strip()
    keywords = {q}
    for group in SEARCH_SYNONYM_GROUPS:
        if any(kw in q for kw in group):
            keywords.update(group)
    return list(keywords)


def list_jobs(filters=None):
    """
    filters 可包含：
      category, city, user_status, status, has_bianzhi, q (标题/医院关键词),
      hide_expired (bool), only_fresh (bool, today added)
    """
    filters = filters or {}
    where = []
    params = []

    if filters.get("category"):
        where.append("category=?")
        params.append(filters["category"])
    # 未指定城市时，默认只返回东莞/广州岗位；指定城市则严格按该城市过滤
    if filters.get("city"):
        where.append("city=?")
        params.append(filters["city"])
    else:
        where.append("city IN (?,?)")
        params.extend(ALLOWED_CITIES)
    if filters.get("user_status"):
        where.append("user_status=?")
        params.append(filters["user_status"])
    if filters.get("status"):
        where.append("status=?")
        params.append(filters["status"])
    if filters.get("has_bianzhi"):
        where.append("has_bianzhi=1")
    if filters.get("hide_expired"):
        where.append("status!='expired'")
    if filters.get("only_fresh"):
        where.append("DATE(added_at)=DATE('now','localtime')")
    if filters.get("q"):
        expanded = expand_search_keywords(filters["q"])
        or_clauses = []
        for kw in expanded:
            or_clauses.append("(title LIKE ? OR hospital LIKE ?)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        if or_clauses:
            where.append("(" + " OR ".join(or_clauses) + ")")

    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY added_at DESC LIMIT 500"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_job(job_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job(job_id, fields):
    """更新字段：user_status, notes, deadline, status, category, hospital, city, reliability"""
    allowed = {"user_status", "notes", "deadline", "status", "category", "hospital", "city", "reliability"}
    sets = []
    params = []
    for k in allowed:
        if k in fields:
            sets.append(f"{k}=?")
            params.append(fields[k])
    if not sets:
        return False
    params.append(job_id)
    with get_db() as conn:
        conn.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", params)
    return True


def delete_job(job_id):
    with get_db() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        new_today = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE DATE(added_at)=DATE('now','localtime')"
        ).fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status='active'").fetchone()["c"]
        saved = conn.execute("SELECT COUNT(*) c FROM jobs WHERE user_status='saved'").fetchone()["c"]
        applied = conn.execute("SELECT COUNT(*) c FROM jobs WHERE user_status='applied'").fetchone()["c"]
        bianzhi = conn.execute("SELECT COUNT(*) c FROM jobs WHERE has_bianzhi=1").fetchone()["c"]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) c FROM jobs WHERE status!='expired' AND city IN (?,?) GROUP BY category ORDER BY c DESC",
            tuple(ALLOWED_CITIES)
        ).fetchall()
        by_city = conn.execute(
            "SELECT city, COUNT(*) c FROM jobs WHERE status!='expired' AND city IN (?,?) GROUP BY city ORDER BY c DESC",
            tuple(ALLOWED_CITIES)
        ).fetchall()
    return {
        "total": total,
        "new_today": new_today,
        "active": active,
        "saved": saved,
        "applied": applied,
        "bianzhi": bianzhi,
        "by_category": [dict(r) for r in by_cat],
        "by_city": [dict(r) for r in by_city],
    }


# ------- 抓取日志 -------

def log_crawl(keyword, found, added, skipped, status="ok", error=None):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO crawl_logs(triggered_at, keyword, found_count, added_count, skipped_count, status, error)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (now_iso(), keyword, found, added, skipped, status, error),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('last_crawl_at', ?)",
            (now_iso(),),
        )


def list_crawl_logs(limit=20):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM crawl_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ------- 设置 -------

def get_setting(key):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
            (key, value),
        )


if __name__ == "__main__":
    is_new = init_db()
    print(f"数据库初始化{'成功' if is_new else '完成'}：{DB_PATH}")
    print("当前统计：", stats())
