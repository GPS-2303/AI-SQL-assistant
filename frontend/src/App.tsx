import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  checkHealth,
  executeSql,
  querySql,
  type ExecuteResponse,
  type QueryResponse,
} from './api/client'
import './App.css'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant' | 'error'
  question?: string
  sql?: string
  kind?: string
  explanation?: string | null
  affectedRows?: number
  columns?: string[]
  rows?: Record<string, unknown>[]
  error?: string
}

type PendingWrite = QueryResponse & { question: string }

const SUGGESTIONS = [
  'Top 5 products by revenue',
  'Orders by status',
  'Customers with the most orders',
  'Show all categories',
]

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function ResultsTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!columns.length) return null

  return (
    <div className="results-wrap">
      <table className="results-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td key={col}>{formatCell(row[col])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="message user">
        <div className="message-label">You</div>
        <div className="message-body">{message.question}</div>
      </div>
    )
  }

  if (message.role === 'error') {
    return (
      <div className="message error">
        <div className="message-label">Error</div>
        <div className="message-body">{message.error}</div>
      </div>
    )
  }

  return (
    <div className="message assistant">
      <div className="message-label">AI SQL</div>
      {message.sql && (
        <pre className="sql-block">{message.sql};</pre>
      )}
      {message.explanation && (
        <div className="explanation">
          <span className="explanation-label">Explanation</span>
          <p>{message.explanation}</p>
        </div>
      )}
      {message.columns && message.rows && message.rows.length > 0 && (
        <ResultsTable columns={message.columns} rows={message.rows} />
      )}
      {message.affectedRows !== undefined && !message.columns?.length && (
        <div className="affected-badge">{message.affectedRows} row(s) affected</div>
      )}
      {message.columns?.length && message.rows?.length === 0 && (
        <div className="muted-inline">No rows returned.</div>
      )}
    </div>
  )
}

function ConfirmModal({
  pending,
  loading,
  onCancel,
  onConfirm,
}: {
  pending: PendingWrite
  loading: boolean
  onCancel: () => void
  onConfirm: (opts: { override: boolean; dangerAck: boolean }) => void
}) {
  const [typedYes, setTypedYes] = useState('')
  const [typedOverride, setTypedOverride] = useState('')
  const [typedDanger, setTypedDanger] = useState('')
  const isDestructive = pending.statement_kind === 'drop' || pending.statement_kind === 'truncate'
  const needsOverride =
    pending.estimated_rows !== null &&
    pending.estimated_rows > 100 &&
    pending.statement_kind !== 'select'

  const canConfirm =
    typedYes.toUpperCase() === 'YES' &&
    (!isDestructive || typedDanger === 'I_UNDERSTAND_DANGER') &&
    (!needsOverride || typedOverride.toUpperCase() === 'OVERRIDE')

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Confirm write operation</h2>
          <p className="modal-sub">
            This {pending.statement_kind.toUpperCase()} statement needs your approval before it runs.
          </p>
        </div>

        {pending.blocked_reason && (
          <div className="alert danger">{pending.blocked_reason}</div>
        )}

        <pre className="sql-block modal-sql">{pending.sql};</pre>

        {pending.explanation && (
          <div className="explanation">
            <span className="explanation-label">What this does</span>
            <p>{pending.explanation}</p>
          </div>
        )}

        {pending.estimated_rows !== null && (
          <div className="estimate-chip">Estimated affected rows: {pending.estimated_rows}</div>
        )}

        {isDestructive && (
          <label className="confirm-field">
            <span>Type <strong>I_UNDERSTAND_DANGER</strong> to continue</span>
            <input
              value={typedDanger}
              onChange={(e) => setTypedDanger(e.target.value)}
              placeholder="I_UNDERSTAND_DANGER"
              disabled={loading}
            />
          </label>
        )}

        {needsOverride && (
          <label className="confirm-field">
            <span>Type <strong>OVERRIDE</strong> (row limit exceeded)</span>
            <input
              value={typedOverride}
              onChange={(e) => setTypedOverride(e.target.value)}
              placeholder="OVERRIDE"
              disabled={loading}
            />
          </label>
        )}

        <label className="confirm-field">
          <span>Type <strong>YES</strong> to execute</span>
          <input
            value={typedYes}
            onChange={(e) => setTypedYes(e.target.value)}
            placeholder="YES"
            disabled={loading || !!pending.blocked_reason}
          />
        </label>

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel} disabled={loading}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!canConfirm || loading || !!pending.blocked_reason}
            onClick={() =>
              onConfirm({
                override: needsOverride && typedOverride.toUpperCase() === 'OVERRIDE',
                dangerAck: isDestructive && typedDanger === 'I_UNDERSTAND_DANGER',
              })
            }
          >
            {loading ? 'Executing…' : 'Execute'}
          </button>
        </div>
      </div>
    </div>
  )
}

function toAssistantMessage(result: ExecuteResponse): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: 'assistant',
    sql: result.sql,
    kind: result.statement_kind,
    explanation: result.explanation,
    affectedRows: result.affected_rows,
    columns: result.columns,
    rows: result.rows,
  }
}

export default function App() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [online, setOnline] = useState<boolean | null>(null)
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    checkHealth().then(setOnline)
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, pendingWrite])

  async function runQuestion(question: string) {
    const trimmed = question.trim()
    if (!trimmed || loading) return

    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', question: trimmed },
    ])
    setInput('')
    setLoading(true)

    try {
      const queryResult = await querySql(trimmed, true)

      if (queryResult.blocked_reason) {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'error',
            error: queryResult.blocked_reason ?? 'This statement was blocked.',
            sql: queryResult.sql,
          },
        ])
        return
      }

      if (queryResult.requires_confirmation) {
        setPendingWrite({ ...queryResult, question: trimmed })
        return
      }

      const result = await executeSql({ sql: queryResult.sql, question: trimmed })
      setMessages((prev) => [...prev, toAssistantMessage(result)])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'error',
          error: err instanceof Error ? err.message : 'Something went wrong',
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  async function confirmPendingWrite(opts: { override: boolean; dangerAck: boolean }) {
    if (!pendingWrite) return
    setLoading(true)

    try {
      const result = await executeSql({
        sql: pendingWrite.sql,
        question: pendingWrite.question,
        confirm: 'YES',
        override: opts.override ? 'OVERRIDE' : '',
        danger_ack: opts.dangerAck ? 'I_UNDERSTAND_DANGER' : '',
      })
      setMessages((prev) => [...prev, toAssistantMessage(result)])
      setPendingWrite(null)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'error',
          error: err instanceof Error ? err.message : 'Execution failed',
        },
      ])
      setPendingWrite(null)
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    void runQuestion(input)
  }

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path
                d="M4 7h16M4 12h10M4 17h14"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
              <circle cx="19" cy="12" r="3" fill="currentColor" opacity="0.8" />
            </svg>
          </div>
          <div>
            <h1>AI SQL</h1>
            <p>Ask in plain English — query or modify your database</p>
          </div>
        </div>
        <div className={`status-pill ${online ? 'online' : online === false ? 'offline' : ''}`}>
          <span className="status-dot" />
          {online === null ? 'Checking…' : online ? 'API connected' : 'API offline'}
        </div>
      </header>

      <main className="chat">
        {messages.length === 0 && !loading && (
          <section className="empty-state">
            <h2>What would you like to know?</h2>
            <p>Describe your question naturally. Reads run instantly; writes ask for confirmation.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="chip" onClick={() => void runQuestion(s)}>
                  {s}
                </button>
              ))}
            </div>
          </section>
        )}

        <div className="messages">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {loading && !pendingWrite && (
            <div className="message assistant loading">
              <div className="message-label">AI SQL</div>
              <div className="typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
      </main>

      <footer className="composer">
        <form onSubmit={handleSubmit} className="composer-form">
          <div className="input-shell">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void runQuestion(input)
                }
              }}
              placeholder="e.g. Show top 5 products by revenue"
              rows={1}
              disabled={loading}
            />
            <button type="submit" className="btn send" disabled={!input.trim() || loading}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M5 12h14M13 6l6 6-6 6"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span>Run</span>
            </button>
          </div>
          <p className="composer-hint">Enter to send · Shift+Enter for new line</p>
        </form>
      </footer>

      {pendingWrite && (
        <ConfirmModal
          pending={pendingWrite}
          loading={loading}
          onCancel={() => setPendingWrite(null)}
          onConfirm={confirmPendingWrite}
        />
      )}
    </div>
  )
}
