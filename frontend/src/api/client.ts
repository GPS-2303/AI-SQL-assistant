const API_BASE = import.meta.env.VITE_API_URL || '/api'
const API_KEY = import.meta.env.VITE_API_KEY || ''

export type QueryResponse = {
  sql: string
  statement_kind: string
  requires_confirmation: boolean
  explanation: string | null
  estimated_rows: number | null
  blocked_reason: string | null
}

export type ExecuteResponse = {
  sql: string
  statement_kind: string
  affected_rows: number
  columns: string[]
  rows: Record<string, unknown>[]
  explanation: string | null
}

function buildHeaders(): HeadersInit {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY
  }
  return headers
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail)) return data.detail.map((d: { msg?: string }) => d.msg).join(', ')
    return response.statusText
  } catch {
    return response.statusText || 'Request failed'
  }
}

export async function querySql(question: string, explain = true): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ question, explain }),
  })
  if (!response.ok) throw new Error(await parseError(response))
  return response.json()
}

export type ExecutePayload = {
  sql: string
  question?: string
  confirm?: string
  override?: string
  danger_ack?: string
  explain?: boolean
}

export async function executeSql(payload: ExecutePayload): Promise<ExecuteResponse> {
  const response = await fetch(`${API_BASE}/execute`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await parseError(response))
  return response.json()
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`)
    return response.ok
  } catch {
    return false
  }
}
