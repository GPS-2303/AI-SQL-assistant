# AI-SQL

Natural-language assistant that turns questions into MySQL statements using Ollama, with safety guards for writes and a FastAPI backend ready for a frontend.

## What it does

1. You ask a question in plain English (CLI or API).
2. Ollama generates a single MySQL statement from the schema in `data/sql/01_schema.sql`.
3. The statement is validated (one statement only, auto-`LIMIT` on `SELECT`).
4. Read queries run immediately; writes require explicit confirmation.

## Quick start

```powershell
python -m venv .venv
pip install -r backend/requirements.txt
copy .env.example .env
```

On Windows, if `Activate.ps1` or `npm` fail with *"running scripts is disabled"*, see [Windows PowerShell](#windows-powershell) below — or use the `.cmd` launchers (no policy change needed).

Set up MySQL with the demo schema and seed:

- `data/sql/01_schema.sql`
- `data/sql/02_seed.sql`

Install and run Ollama, then pull a model:

```powershell
ollama pull llama3.1:8b
```

### CLI

```powershell
python scripts/assistant_cli.py
```

### API (for frontend)

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Or double-click / run: `scripts\run-backend.cmd`

Open interactive docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness check (no auth) |
| GET | `/schema` | Database schema SQL for UI context |
| POST | `/query` | NL → SQL generation + validation |
| POST | `/ask` | NL → SQL + auto-execute for `SELECT` |
| POST | `/execute` | Run SQL (writes need confirmation fields) |
| GET | `/audit` | Recent audit log rows |

If `API_KEY` is set in `.env`, send header `X-API-Key` on all endpoints except `/health`.

CORS is enabled for origins in `CORS_ORIGINS` (default: `http://localhost:5173`, `http://localhost:3000`).

## Frontend integration flow

**Read-only chat (simplest):**

```
POST /ask  { "question": "top 5 products by revenue" }
→ { sql, columns, rows, affected_rows }
```

**Writes (two-step, mirrors CLI safety):**

```
POST /query  { "question": "...", "explain": true }
→ review sql, explanation, estimated_rows, blocked_reason

POST /execute  {
  "sql": "...",
  "question": "original question",
  "confirm": "YES",
  "override": "OVERRIDE",          // if estimated_rows > MAX_WRITE_ROWS
  "danger_ack": "I_UNDERSTAND_DANGER"  // for DROP/TRUNCATE
}
```

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Or double-click / run: `frontend\run-dev.cmd`

Open [http://localhost:5173](http://localhost:5173). The dev server proxies API calls to `http://localhost:8000` via `/api`.

Make sure the FastAPI backend is running first:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Optional: copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_KEY` if your backend uses `API_KEY`.

## Windows PowerShell

If you see **"running scripts is disabled on this system"** when using `Activate.ps1` or `npm`:

**Option A — use `.cmd` (no settings change):**

```powershell
# Backend (from project root)
scripts\run-backend.cmd

# Frontend (separate terminal)
frontend\run-dev.cmd
```

**Option B — call `.cmd` tools directly:**

```powershell
.\.venv\Scripts\activate.bat          # instead of Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd install
npm.cmd run dev
```

**Option C — allow local scripts once (recommended long-term):**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then `Activate.ps1` and `npm` work normally. You only need to run Option C once per Windows user account.

## Tests

```powershell
python -m unittest discover -s backend/tests -p "test_*.py" -v
python scripts/test_assistant_cli_smoke.py
```

## More detail

See [docs/assistant_setup.md](docs/assistant_setup.md) for full setup, env vars, and example request bodies.

## Publish to GitHub

The repo is set up to exclude secrets and generated files (`.env`, `.venv`, `node_modules`, `dist`). Before your first push:

1. Do **not** commit `.env` or `frontend/.env` — use the `.env.example` files instead.
2. Initialize and push:

```powershell
cd "D:\RASPBERRY PI\AI-SQL"
git init
git add .
git status
git commit -m "Initial commit: AI SQL assistant"
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

Review `git status` before committing and confirm no `.env` files are staged.
