import { useEffect, useRef, useState, type FormEvent } from 'react'

type Role = 'user' | 'assistant'

interface ToolCall {
  name: string
  args: Record<string, unknown>
}

interface Message {
  role: Role
  content: string
  toolCalls?: ToolCall[]
}

interface ChatResponse {
  reply: string
  tool_calls: ToolCall[]
}

const API_URL = import.meta.env.VITE_API_URL as string

const EXAMPLES = [
  'What’s the weather tomorrow?',
  'Note that I need milk',
  'What notes do I have?',
]

// "get_weather · Sigmaringen · 1": tool name, then its argument values
function formatToolCall({ name, args }: ToolCall): string {
  const values = Object.values(args)
    .filter((v) => v !== null && v !== undefined && v !== '')
    .map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v)))
  return [name, ...values].join(' · ')
}

async function sendChat(messages: Message[]): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.map(({ role, content }) => ({ role, content })),
    }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending, error])

  async function send(text: string) {
    const content = text.trim()
    if (!content || pending) return

    const next: Message[] = [...messages, { role: 'user', content }]
    setMessages(next)
    setInput('')
    setError(null)
    setPending(true)
    try {
      const data = await sendChat(next)
      setMessages([
        ...next,
        { role: 'assistant', content: data.reply, toolCalls: data.tool_calls },
      ])
    } catch {
      setError('Couldn’t reach Assist. Try again.')
    } finally {
      setPending(false)
      inputRef.current?.focus()
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    send(input)
  }

  const empty = messages.length === 0 && !pending && !error

  return (
    <div className="app">
      <header className="column header">Assist</header>

      <main className="scroll">
        <div className="column thread" aria-live="polite">
          {empty && (
            <div className="empty">
              <p>Ask about your notes or the weather.</p>
              <div className="examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex} className="example" onClick={() => send(ex)}>
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="msg-user">
                {m.content}
              </div>
            ) : (
              <div key={i} className="msg-assistant">
                {m.content}
                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="tools">
                    {m.toolCalls.map((tc, j) => (
                      <span key={j} className="tool">
                        {formatToolCall(tc)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ),
          )}

          {pending && (
            <div className="dots" aria-label="Waiting for reply">
              <span />
              <span />
              <span />
            </div>
          )}

          {error && <div className="error">{error}</div>}

          <div ref={endRef} />
        </div>
      </main>

      <form className="column composer" onSubmit={onSubmit}>
        <div className="field">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Message Assist"
            aria-label="Message"
            autoFocus
          />
          <button
            type="submit"
            className="icon-btn send"
            disabled={!input.trim() || pending}
            aria-label="Send"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
        <button
          type="button"
          className="icon-btn mic"
          disabled
          aria-label="Voice input (coming soon)"
          title="Voice input (coming soon)"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="3" width="6" height="12" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        </button>
      </form>
    </div>
  )
}
