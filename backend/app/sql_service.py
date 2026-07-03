import os
import re
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import mysql.connector
import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "data" / "sql" / "01_schema.sql"
SQL_VERB_RE = re.compile(
    r"(?is)\b(select|insert|update|delete|replace|create|drop|alter|truncate|rename|show|describe|explain|use)\b"
)


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    return {
        "db_host": os.getenv("DB_HOST"),
        "db_port": int(os.getenv("DB_PORT", "3306")),
        "db_user": os.getenv("DB_USER"),
        "db_password": os.getenv("DB_PASSWORD"),
        "db_name": os.getenv("DB_NAME"),
        "db_write_user": os.getenv("DB_WRITE_USER") or os.getenv("DB_USER"),
        "db_write_password": os.getenv("DB_WRITE_PASSWORD") or os.getenv("DB_PASSWORD"),
        "max_write_rows": int(os.getenv("MAX_WRITE_ROWS", "100")),
        "allow_full_table_write": os.getenv("ALLOW_FULL_TABLE_WRITE", "false").lower() == "true",
        "audit_log_enabled": os.getenv("AUDIT_LOG_ENABLED", "true").lower() == "true",
        "audit_actor": os.getenv("AUDIT_ACTOR", "fastapi"),
        "api_key": os.getenv("API_KEY", ""),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL"),
        "ollama_model": os.getenv("OLLAMA_MODEL"),
        "cors_origins": [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
            if origin.strip()
        ],
    }


def json_safe_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def json_safe_rows(rows: list[dict]) -> list[dict]:
    return [{key: json_safe_value(val) for key, val in row.items()} for row in rows]


def read_schema_text() -> str:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    return SCHEMA_PATH.read_text(encoding="utf-8")


def build_prompt(schema_sql: str, question: str) -> str:
    return f"""
You are a MySQL SQL assistant for a database named ai_sql_dev.
Return ONLY one valid MySQL SQL statement that answers the question.

Rules:
- Use only tables/columns from this schema.
- Output only one SQL statement.
- If the user asks to modify data or schema, output the needed MySQL statement (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/etc).
- Prefer explicit JOINs.
- If the statement is a SELECT and the user does not request another limit, add a LIMIT <= 50.
- Return plain SQL text only (no markdown, no explanation).

Schema:
{schema_sql}

Question:
{question}
""".strip()


def call_ollama(base_url: str, model: str, prompt: str) -> str:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


def explain_sql(cfg: dict, sql: str) -> str:
    prompt = f"""
Explain the following MySQL statement in plain language for a non-technical user.
Keep it short (max 3 bullet points) and include possible impact/risk.
Do not suggest additional SQL. Do not include markdown code fences.

SQL:
{sql}
""".strip()
    return call_ollama(cfg["ollama_base_url"], cfg["ollama_model"], prompt)


def clean_sql(raw: str) -> str:
    sql = raw.strip().strip("`")
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE).strip()
    sql = re.sub(r"^```\s*", "", sql).strip()
    sql = re.sub(r"\s*```$", "", sql).strip()
    return sql


def extract_first_statement(sql: str) -> str:
    match = SQL_VERB_RE.search(sql)
    if not match:
        return sql.strip()
    candidate = sql[match.start() :].strip()
    semicolon_pos = candidate.find(";")
    if semicolon_pos != -1:
        return candidate[: semicolon_pos + 1].strip()
    return candidate


def statement_kind(sql: str) -> str:
    m = re.match(r"(?is)^\s*([a-z]+)\b", sql)
    return (m.group(1).lower() if m else "").strip()


def has_where_clause(sql: str) -> bool:
    return re.search(r"(?is)\bwhere\b", sql) is not None


def validate_and_normalize_sql(sql: str) -> str:
    raw = sql.strip()
    if ";" in raw:
        first = raw.find(";")
        if raw[first + 1 :].strip():
            raise ValueError("Multiple SQL statements are not allowed.")

    sql = extract_first_statement(sql)
    if ";" in sql[:-1]:
        raise ValueError("Multiple SQL statements are not allowed.")

    sql = sql.rstrip(";").strip()
    kind = statement_kind(sql)
    if not kind:
        raise ValueError("Could not detect SQL statement type.")

    if kind == "select" and not re.search(r"(?i)\blimit\b", sql):
        sql = f"{sql} LIMIT 50"
    return sql


def _connect(cfg: dict, use_writer: bool):
    user = cfg["db_write_user"] if use_writer else cfg["db_user"]
    password = cfg["db_write_password"] if use_writer else cfg["db_password"]
    return mysql.connector.connect(
        host=cfg["db_host"],
        port=cfg["db_port"],
        user=user,
        password=password,
        database=cfg["db_name"],
    )


def run_sql(cfg: dict, sql: str, *, use_writer: bool) -> tuple[list[str], list[dict], int]:
    conn = _connect(cfg, use_writer)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql)
        rows = cur.fetchall() if cur.description else []
        columns = [col[0] for col in cur.description] if cur.description else []
        if not cur.description:
            conn.commit()
        return columns, json_safe_rows(rows), cur.rowcount
    finally:
        conn.close()


def estimate_affected_rows(cfg: dict, sql: str) -> int:
    conn = _connect(cfg, use_writer=True)
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(sql)
        affected = cur.rowcount
        conn.rollback()
        return affected
    finally:
        conn.close()


def ensure_audit_table(cfg: dict) -> None:
    if not cfg["audit_log_enabled"]:
        return
    conn = _connect(cfg, use_writer=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sql_audit_log (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
              actor VARCHAR(100) NOT NULL,
              question_text TEXT NOT NULL,
              sql_text LONGTEXT NULL,
              statement_kind VARCHAR(32) NULL,
              status ENUM('executed', 'cancelled', 'blocked', 'error') NOT NULL,
              used_writer TINYINT(1) NOT NULL DEFAULT 0,
              estimated_rows INT NULL,
              affected_rows INT NULL,
              error_message TEXT NULL,
              explanation_text TEXT NULL,
              KEY idx_sql_audit_log_created_at (created_at),
              KEY idx_sql_audit_log_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        conn.commit()
    finally:
        conn.close()


def write_audit_log(
    cfg: dict,
    *,
    question: str,
    sql_text: str,
    kind: str,
    status: str,
    used_writer: bool,
    estimated_rows: int | None,
    affected_rows: int | None,
    error_message: str = "",
    explanation_text: str = "",
) -> None:
    if not cfg["audit_log_enabled"]:
        return
    conn = _connect(cfg, use_writer=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sql_audit_log (
              actor, question_text, sql_text, statement_kind, status, used_writer,
              estimated_rows, affected_rows, error_message, explanation_text
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cfg["audit_actor"],
                question,
                sql_text or None,
                kind or None,
                status,
                1 if used_writer else 0,
                estimated_rows,
                affected_rows,
                error_message or None,
                explanation_text or None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def safe_write_audit_log(*args, **kwargs) -> None:
    try:
        write_audit_log(*args, **kwargs)
    except Exception:
        pass
