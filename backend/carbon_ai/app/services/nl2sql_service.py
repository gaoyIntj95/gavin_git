from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.services.llm_gateway import chat_messages

logger = logging.getLogger(__name__)


# Read-only allowlist for NL2SQL.
ALLOWED_TABLES = {
    "projects",
    "emission_sources",
    "factor_library",
    "uncertainty_assessments",
    "evidence_records",
    "cbam_data",
    "carbon_market",
    "industry_news",
    "reports",
    "chat_history",
    "chat_sessions",
    "knowledge_documents",
    "quick_questions",
    "users",
}
MAX_RESULT_LIMIT = 200
DEFAULT_RESULT_LIMIT = 50


def _extract_sql(text_content: str) -> str:
    if not text_content:
        return ""
    match = re.search(r"```sql\s*(.*?)\s*```", text_content, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text_content.strip()


def _normalize_sql(sql: str) -> str:
    normalized = (sql or "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.rstrip(";").strip()
    return normalized


def _extract_table_names(sql: str) -> set[str]:
    sql_lower = sql.lower()
    pattern = r"(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    return {name.strip() for name in re.findall(pattern, sql_lower)}


def _append_or_clamp_limit(sql: str, default_limit: int = DEFAULT_RESULT_LIMIT) -> str:
    limit_match = re.search(r"\blimit\s+(\d+)\b", sql, re.IGNORECASE)
    if not limit_match:
        return f"{sql} LIMIT {default_limit}"
    try:
        raw_limit = int(limit_match.group(1))
    except Exception:
        raw_limit = default_limit
    clamped = min(max(raw_limit, 1), MAX_RESULT_LIMIT)
    return re.sub(r"\blimit\s+\d+\b", f"LIMIT {clamped}", sql, flags=re.IGNORECASE)


def _validate_sql(sql: str) -> tuple[bool, str]:
    if not sql:
        return False, "SQL 为空"

    lowered = sql.lower()
    if not lowered.startswith("select "):
        return False, "仅允许 SELECT 查询"

    forbidden_tokens = [
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " truncate ",
        " create ",
        " replace ",
        " grant ",
        " revoke ",
        " call ",
        " execute ",
        " attach ",
        " detach ",
        " pragma ",
        " into outfile ",
        " load_file(",
        "--",
        "/*",
        "*/",
    ]
    padded = f" {lowered} "
    if any(token in padded for token in forbidden_tokens):
        return False, "SQL 包含不允许的关键字或注释"

    tables = _extract_table_names(sql)
    if not tables:
        return False, "SQL 未解析到 FROM/JOIN 表"
    disallowed = tables.difference(ALLOWED_TABLES)
    if disallowed:
        return False, f"SQL 访问了未授权表: {', '.join(sorted(disallowed))}"
    return True, "ok"


def _build_schema_snapshot(db: Session) -> str:
    try:
        inspector = inspect(db.bind)
        existing_tables = set(inspector.get_table_names())
        lines: list[str] = []
        for table in sorted(ALLOWED_TABLES.intersection(existing_tables)):
            cols = inspector.get_columns(table)
            col_names = [str(c.get("name")) for c in cols][:24]
            lines.append(f"{table}({', '.join(col_names)})")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Build schema snapshot failed: %s", exc)
        return ""


def _generate_sql_by_llm(db: Session, question: str, project_id: int | None = None) -> str:
    schema_text = _build_schema_snapshot(db)
    project_hint = ""
    if project_id is not None:
        project_hint = (
            f"\n如果问题涉及项目数据，优先使用 project_id = {project_id} 作为筛选条件。"
        )

    system_prompt = (
        "你是一个 MySQL 查询助手。"
        "你只能输出单条 SELECT 语句，不允许输出解释、不允许输出多条语句。"
        "结果必须可直接执行。"
    )
    user_prompt = (
        "数据库可用表结构如下：\n"
        f"{schema_text}\n\n"
        f"用户问题：{question}\n"
        f"{project_hint}\n\n"
        "请生成一条安全的 SELECT SQL。"
    )

    response = chat_messages(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        task="agent",
        contains_sensitive=False,
    )
    return _normalize_sql(_extract_sql(response))


def query_by_nl2sql(
    db: Session,
    question: str,
    project_id: int | None = None,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    if not question or not question.strip():
        return {"error": "问题为空"}

    try:
        sql = _generate_sql_by_llm(db, question=question, project_id=project_id)
        sql = _append_or_clamp_limit(sql, default_limit=min(max(limit, 1), MAX_RESULT_LIMIT))
        ok, reason = _validate_sql(sql)
        if not ok:
            return {"error": f"SQL 安全校验失败: {reason}", "generated_sql": sql}

        result = db.execute(text(sql))
        rows_raw = result.fetchall()
        columns = list(result.keys())
        rows = [dict(zip(columns, row, strict=False)) for row in rows_raw]
        return {
            "sql": sql,
            "row_count": len(rows),
            "columns": columns,
            "rows": rows,
        }
    except Exception as exc:
        logger.error("NL2SQL query failed: %s", exc)
        return {"error": f"NL2SQL 执行失败: {exc}"}

