import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.sql_service import (  # noqa: E402
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


def print_rows(columns: list[str], rows: list[dict], max_rows: int = 20) -> None:
    if not rows:
        print("No rows returned.")
        return
    print(" | ".join(columns))
    print("-" * 80)
    for row in rows[:max_rows]:
        print(" | ".join(str(row.get(col, "")) for col in columns))
    if len(rows) > max_rows:
        print(f"... ({len(rows) - max_rows} more rows)")


def main() -> None:
    cfg = load_config()
    schema_text = read_schema_text()
    if cfg["audit_log_enabled"]:
        try:
            ensure_audit_table(cfg)
        except Exception as exc:
            print(f"Warning: audit table unavailable: {exc}")

    print("AI SQL Assistant (Ollama + MySQL)")
    print("Type a question, or 'exit' to quit.")

    while True:
        question = input("\nQuestion> ").strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        raw_sql = ""
        candidate_sql = ""
        final_sql = ""
        kind = ""
        explanation = ""
        estimated_rows = None
        try:
            prompt = build_prompt(schema_text, question)
            raw_sql = call_ollama(cfg["ollama_base_url"], cfg["ollama_model"], prompt)
            candidate_sql = clean_sql(raw_sql)
            final_sql = validate_and_normalize_sql(candidate_sql)

            kind = statement_kind(final_sql)
            needs_confirm = kind != "select"
            if needs_confirm:
                print("\nProposed SQL (confirmation required):")
                print(final_sql + ";")

                want_explain = input("Explain this SQL in plain language? (y/N)> ").strip().lower()
                if want_explain in {"y", "yes"}:
                    explanation = explain_sql(cfg, final_sql)
                    print("\nWhat this SQL does:")
                    print(explanation)

                if kind in {"update", "delete"} and not cfg["allow_full_table_write"] and not has_where_clause(final_sql):
                    message = (
                        "Unsafe write blocked: UPDATE/DELETE without WHERE. "
                        "Set ALLOW_FULL_TABLE_WRITE=true to bypass."
                    )
                    print(message)
                    safe_write_audit_log(
                        cfg,
                        question=question,
                        sql_text=final_sql,
                        kind=kind,
                        status="blocked",
                        used_writer=True,
                        estimated_rows=None,
                        affected_rows=None,
                        error_message=message,
                        explanation_text=explanation,
                    )
                    continue

                if kind in {"update", "delete"}:
                    estimated_rows = estimate_affected_rows(cfg, final_sql)
                    print(f"\nEstimated affected rows: {estimated_rows}")
                    if estimated_rows > cfg["max_write_rows"]:
                        override = input(
                            f"Estimated rows exceed MAX_WRITE_ROWS={cfg['max_write_rows']}. "
                            "Type OVERRIDE to continue, anything else to cancel> "
                        ).strip()
                        if override.upper() != "OVERRIDE":
                            print("Cancelled.")
                            safe_write_audit_log(
                                cfg,
                                question=question,
                                sql_text=final_sql,
                                kind=kind,
                                status="cancelled",
                                used_writer=True,
                                estimated_rows=estimated_rows,
                                affected_rows=None,
                                error_message="Cancelled by user at MAX_WRITE_ROWS guard.",
                                explanation_text=explanation,
                            )
                            continue

                if kind in {"drop", "truncate"}:
                    strong_confirm = input(
                        "Destructive SQL detected. Type I_UNDERSTAND_DANGER to continue> "
                    ).strip()
                    if strong_confirm != "I_UNDERSTAND_DANGER":
                        print("Cancelled.")
                        safe_write_audit_log(
                            cfg,
                            question=question,
                            sql_text=final_sql,
                            kind=kind,
                            status="cancelled",
                            used_writer=True,
                            estimated_rows=estimated_rows,
                            affected_rows=None,
                            error_message="Cancelled by user at destructive confirmation.",
                            explanation_text=explanation,
                        )
                        continue

                confirm = input("Type YES to execute, anything else to cancel> ").strip()
                if confirm.upper() != "YES":
                    print("Cancelled.")
                    safe_write_audit_log(
                        cfg,
                        question=question,
                        sql_text=final_sql,
                        kind=kind,
                        status="cancelled",
                        used_writer=True,
                        estimated_rows=estimated_rows,
                        affected_rows=None,
                        error_message="Cancelled by user at final confirmation.",
                        explanation_text=explanation,
                    )
                    continue

            columns, rows, rowcount = run_sql(cfg, final_sql, use_writer=needs_confirm)

            print("\nGenerated SQL:")
            print(final_sql + ";")
            print("\nResults:")
            if columns:
                print_rows(columns, rows)
            else:
                print(f"Affected rows: {rowcount}")
            safe_write_audit_log(
                cfg,
                question=question,
                sql_text=final_sql,
                kind=kind,
                status="executed",
                used_writer=needs_confirm,
                estimated_rows=estimated_rows,
                affected_rows=rowcount if not columns else len(rows),
                explanation_text=explanation,
            )
        except Exception as exc:
            if final_sql:
                print("\nGenerated SQL (for debug):")
                print(final_sql + ";")
            elif candidate_sql:
                print("\nModel output (cleaned, for debug):")
                print(candidate_sql)
            elif raw_sql:
                print("\nModel output (raw, for debug):")
                print(raw_sql)
            print(f"Error: {exc}")
            safe_write_audit_log(
                cfg,
                question=question,
                sql_text=final_sql or candidate_sql or raw_sql,
                kind=kind,
                status="error",
                used_writer=(kind != "select"),
                estimated_rows=estimated_rows,
                affected_rows=None,
                error_message=str(exc),
                explanation_text=explanation,
            )


if __name__ == "__main__":
    main()
