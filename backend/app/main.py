import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .schemas import ExecuteRequest, ExecuteResponse, QueryRequest, QueryResponse
from .sql_service import (
    build_prompt,
    call_ollama,
    clean_sql,
    ensure_audit_table,
    estimate_affected_rows,
    explain_sql,
    has_where_clause,
    load_config,
    read_schema_text,
    run_sql,
    safe_write_audit_log,
    statement_kind,
    validate_and_normalize_sql,
)


cfg = load_config()
schema_text = read_schema_text()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_audit_table(cfg)
    yield


app = FastAPI(title="AI SQL Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected_api_key = cfg.get("api_key", "")
    if not expected_api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _audit_question(payload: ExecuteRequest) -> str:
    return (payload.question or "").strip() or "direct_execute"


def _generate_query_response(payload: QueryRequest) -> QueryResponse:
    prompt = build_prompt(schema_text, payload.question)
    raw_sql = call_ollama(cfg["ollama_base_url"], cfg["ollama_model"], prompt)
    final_sql = validate_and_normalize_sql(clean_sql(raw_sql))
    kind = statement_kind(final_sql)
    needs_confirm = kind != "select"

    explanation = explain_sql(cfg, final_sql) if (payload.explain and needs_confirm) else None
    estimated_rows = estimate_affected_rows(cfg, final_sql) if kind in {"update", "delete"} else None

    blocked_reason = None
    if kind in {"update", "delete"} and not cfg["allow_full_table_write"] and not has_where_clause(final_sql):
        blocked_reason = (
            "Unsafe write blocked: UPDATE/DELETE without WHERE. "
            "Set ALLOW_FULL_TABLE_WRITE=true to bypass."
        )

    return QueryResponse(
        sql=final_sql,
        statement_kind=kind,
        requires_confirmation=needs_confirm,
        explanation=explanation,
        estimated_rows=estimated_rows,
        blocked_reason=blocked_reason,
    )


@app.get("/schema")
def get_schema(_: None = Depends(require_api_key)) -> dict:
    return {"database": cfg["db_name"], "schema_sql": schema_text}


@app.post("/query", response_model=QueryResponse)
def query_sql(payload: QueryRequest, _: None = Depends(require_api_key)) -> QueryResponse:
    try:
        return _generate_query_response(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ask", response_model=ExecuteResponse)
def ask_sql(payload: QueryRequest, _: None = Depends(require_api_key)) -> ExecuteResponse:
    """Generate SQL from natural language and auto-execute SELECT statements."""
    try:
        query_result = _generate_query_response(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if query_result.statement_kind != "select":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Statement kind '{query_result.statement_kind}' requires confirmation. "
                "Use POST /execute with the returned SQL and confirmation fields."
            ),
        )

    execute_payload = ExecuteRequest(sql=query_result.sql, question=payload.question)
    return execute_sql(execute_payload, _)


@app.post("/execute", response_model=ExecuteResponse)
def execute_sql(payload: ExecuteRequest, _: None = Depends(require_api_key)) -> ExecuteResponse:
    sql = validate_and_normalize_sql(payload.sql)
    kind = statement_kind(sql)
    needs_confirm = kind != "select"
    audit_question = _audit_question(payload)
    explanation = explain_sql(cfg, sql) if (payload.explain and needs_confirm) else None
    estimated_rows = None

    if needs_confirm and payload.confirm.upper() != "YES":
        safe_write_audit_log(
            cfg,
            question=audit_question,
            sql_text=sql,
            kind=kind,
            status="cancelled",
            used_writer=True,
            estimated_rows=None,
            affected_rows=None,
            error_message="Missing YES confirmation.",
            explanation_text=explanation or "",
        )
        raise HTTPException(status_code=400, detail="Write statements require confirm='YES'.")

    if kind in {"update", "delete"} and not cfg["allow_full_table_write"] and not has_where_clause(sql):
        safe_write_audit_log(
            cfg,
            question=audit_question,
            sql_text=sql,
            kind=kind,
            status="blocked",
            used_writer=True,
            estimated_rows=None,
            affected_rows=None,
            error_message="Blocked UPDATE/DELETE without WHERE.",
            explanation_text=explanation or "",
        )
        raise HTTPException(status_code=400, detail="Blocked UPDATE/DELETE without WHERE.")

    if kind in {"update", "delete"}:
        estimated_rows = estimate_affected_rows(cfg, sql)
        if estimated_rows > cfg["max_write_rows"] and payload.override.upper() != "OVERRIDE":
            safe_write_audit_log(
                cfg,
                question=audit_question,
                sql_text=sql,
                kind=kind,
                status="cancelled",
                used_writer=True,
                estimated_rows=estimated_rows,
                affected_rows=None,
                error_message="Exceeded MAX_WRITE_ROWS without OVERRIDE.",
                explanation_text=explanation or "",
            )
            raise HTTPException(
                status_code=400,
                detail=f"Estimated rows {estimated_rows} exceed MAX_WRITE_ROWS={cfg['max_write_rows']}.",
            )

    if kind in {"drop", "truncate"} and payload.danger_ack != "I_UNDERSTAND_DANGER":
        safe_write_audit_log(
            cfg,
            question=audit_question,
            sql_text=sql,
            kind=kind,
            status="cancelled",
            used_writer=True,
            estimated_rows=estimated_rows,
            affected_rows=None,
            error_message="Missing danger acknowledgment.",
            explanation_text=explanation or "",
        )
        raise HTTPException(status_code=400, detail="Destructive statements require danger_ack.")

    try:
        columns, rows, rowcount = run_sql(cfg, sql, use_writer=needs_confirm)
        affected_rows = rowcount if not columns else len(rows)
        safe_write_audit_log(
            cfg,
            question=audit_question,
            sql_text=sql,
            kind=kind,
            status="executed",
            used_writer=needs_confirm,
            estimated_rows=estimated_rows,
            affected_rows=affected_rows,
            explanation_text=explanation or "",
        )
        return ExecuteResponse(
            sql=sql,
            statement_kind=kind,
            affected_rows=affected_rows,
            columns=columns,
            rows=rows,
            explanation=explanation,
        )
    except Exception as exc:
        safe_write_audit_log(
            cfg,
            question=audit_question,
            sql_text=sql,
            kind=kind,
            status="error",
            used_writer=needs_confirm,
            estimated_rows=estimated_rows,
            affected_rows=None,
            error_message=str(exc),
            explanation_text=explanation or "",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/audit")
def audit_log(limit: int = Query(default=20, ge=1, le=200), _: None = Depends(require_api_key)) -> dict:
    sql = (
        "SELECT id, created_at, actor, question_text, statement_kind, status, used_writer, "
        "estimated_rows, affected_rows, error_message "
        f"FROM sql_audit_log ORDER BY id DESC LIMIT {limit}"
    )
    columns, rows, _ = run_sql(cfg, sql, use_writer=False)
    return {"columns": columns, "rows": rows}
