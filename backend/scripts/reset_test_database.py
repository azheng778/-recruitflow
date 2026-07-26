from __future__ import annotations

import sys

import pymysql

from app.config import settings


SAFE_TEST_DATABASE = "hr_recruitment_test"


def main() -> None:
    name = settings.db_name
    expected = settings.test_db_name
    if settings.app_env != "test" or name != expected:
        raise RuntimeError("拒绝重建：必须满足 APP_ENV=test 且 DB_NAME=TEST_DB_NAME")
    if (
        name != SAFE_TEST_DATABASE
        or not name.endswith("_test")
        or name in {"hr_recruitment", "langchain_db"}
    ):
        raise RuntimeError(f"拒绝重建不安全的数据库目标：{name}")

    connection = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_username,
        password=settings.db_password,
        charset=settings.db_charset,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        connection.close()
    print(f"TEST_DATABASE_RESET_OK name={name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"TEST_DATABASE_RESET_FAILED {exc}", file=sys.stderr)
        raise
