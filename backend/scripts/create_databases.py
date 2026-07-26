from __future__ import annotations

import pymysql

from app.config import settings


def main() -> None:
    for name in (settings.db_name, settings.test_db_name):
        settings.validate_database_boundary(name)
        if name not in {"hr_recruitment", "hr_recruitment_test"}:
            raise RuntimeError(f"Refusing unexpected database name: {name}")
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_username,
        password=settings.db_password,
        charset=settings.db_charset,
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            for name in (settings.db_name, settings.test_db_name):
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
    finally:
        conn.close()
    print(f"DATABASES_READY {settings.db_name}, {settings.test_db_name}")


if __name__ == "__main__":
    main()

