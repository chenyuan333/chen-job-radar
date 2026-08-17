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
    "default_keywords": "东莞 体检科医师\n东莞 心电图医师\n东莞 全科医师\n东莞 校医\n东莞 疾控\n东莞 AI医疗",
    "default_city": "东莞",
    "default_categories": '["体检科","心电图","社区医师","校医","卫健委","疾控中心","AI医疗","其他"]',
    "schedule_enabled": "false",
    "last_crawl_at": "",
}


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
    if filters.get("city"):
        where.append("city=?")
        params.append(filters["city"])
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
        where.append("(title LIKE ? OR hospital LIKE ?)")
        kw = f"%{filters['q']}%"
        params.extend([kw, kw])

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
    """更新字段：user_status, notes, deadline, status, category, hospital"""
    allowed = {"user_status", "notes", "deadline", "status", "category", "hospital", "reliability"}
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
            "SELECT category, COUNT(*) c FROM jobs WHERE status!='expired' GROUP BY category ORDER BY c DESC"
        ).fetchall()
        by_city = conn.execute(
            "SELECT city, COUNT(*) c FROM jobs WHERE status!='expired' GROUP BY city ORDER BY c DESC"
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
