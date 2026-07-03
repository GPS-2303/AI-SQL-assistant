from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    explain: bool = False


class ExecuteRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    question: str | None = None
    confirm: str = ""
    override: str = ""
    danger_ack: str = ""
    explain: bool = False


class QueryResponse(BaseModel):
    sql: str
    statement_kind: str
    requires_confirmation: bool
    explanation: str | None = None
    estimated_rows: int | None = None
    blocked_reason: str | None = None


class ExecuteResponse(BaseModel):
    sql: str
    statement_kind: str
    affected_rows: int
    columns: list[str]
    rows: list[dict]
    explanation: str | None = None
