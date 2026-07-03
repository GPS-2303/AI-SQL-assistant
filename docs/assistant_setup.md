# Ollama Assistant Setup

## 1) Install Python deps

From project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

## 2) Create .env

Copy `.env.example` to `.env` and adjust values if needed.

Recommended keys:

- `DB_USER` / `DB_PASSWORD`: read-only user.
- `DB_WRITE_USER` / `DB_WRITE_PASSWORD`: write-capable user for non-SELECT SQL.
- `MAX_WRITE_ROWS`: guardrail for update/delete row impact (default `100`).
- `ALLOW_FULL_TABLE_WRITE`: block update/delete without `WHERE` unless `true`.
- `AUDIT_LOG_ENABLED`: enable DB audit logging table writes.
- `AUDIT_ACTOR`: source tag written to audit rows (for example `local_cli` or `fastapi`).
- `API_KEY`: optional shared key required by FastAPI for `/query`, `/execute`, and `/audit`.

## 3) Install and run Ollama

1. Install Ollama from [https://ollama.com/](https://ollama.com/)
2. Pull a model:

```powershell
ollama pull llama3.1:8b
```

3. Keep Ollama running in background (default URL `http://localhost:11434`).

## 4) Run the assistant

```powershell
python scripts/assistant_cli.py
```

Ask questions like:

- `top 5 products by revenue`
- `orders by status`
- `customers with most orders`

## 5) Run FastAPI backend

From project root:

```powershell
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Key endpoints:

- `GET /health`
- `GET /schema` (schema SQL for frontend context panels)
- `POST /query` (generate and validate SQL from natural language)
- `POST /ask` (generate SQL and auto-execute `SELECT` statements)
- `POST /execute` (execute SQL with confirmation fields for writes)
- `GET /audit` (latest audit events)

If `API_KEY` is set in `.env`, send header `X-API-Key: <your key>` for all endpoints except `/health`.

For browser frontends, set `CORS_ORIGINS` in `.env` (default includes `http://localhost:5173` and `http://localhost:3000`).

Example `POST /query` body:

```json
{
  "question": "top 5 products by revenue",
  "explain": false
}
```

Example `POST /execute` body for write SQL:

```json
{
  "sql": "UPDATE customers SET country = 'US' WHERE id = 1",
  "confirm": "YES",
  "override": "",
  "danger_ack": "",
  "explain": true
}
```
