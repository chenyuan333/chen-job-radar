"""
一次性清理：把数据库里实际不属于东莞/广州的岗位标为 expired，
并重新校正剩余岗位的城市字段。
"""
import database
import parser


def main():
    database.init_db()
    jobs = database.list_jobs(filters={})
    updated = 0
    expired = 0
    already_ok = 0

    for j in jobs:
        text = " ".join([
            j.get("title", ""),
            j.get("hospital", ""),
            j.get("description", ""),
            j.get("source", ""),
        ])
        if parser.has_wrong_region(text):
            database.update_job(j["id"], {"status": "expired"})
            expired += 1
            continue

        chosen = parser.pick_city(text)
        if not chosen:
            # 没有明确城市信息，也标过期
            database.update_job(j["id"], {"status": "expired"})
            expired += 1
            continue

        if j.get("city") != chosen:
            database.update_job(j["id"], {"city": chosen})
            updated += 1
        else:
            already_ok += 1

    print(f"总计岗位: {len(jobs)}")
    print(f"标为 expired: {expired}")
    print(f"校正城市: {updated}")
    print(f"原本正确: {already_ok}")
    print("清理后统计:", database.stats())


if __name__ == "__main__":
    main()
