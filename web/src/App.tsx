import { useEffect, useRef, useState, type FormEvent } from "react";

type Role = "user" | "assistant";

interface ToolCall {
  name: string;
  args: Record<string, unknown>;
}

interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
}

interface ChatResponse {
  reply: string;
  tool_calls: ToolCall[];
}

const API_URL = import.meta.env.VITE_API_URL as string;

const EXAMPLES = [
  "What’s the weather tomorrow?",
  "Note that I need milk",
  "What notes do I have?",
];

// "get_weather · Sigmaringen · 1": tool name, then its argument values
function formatToolCall({ name, args }: ToolCall): string {
  const values = Object.values(args)
    .filter((v) => v !== null && v !== undefined && v !== "")
    .map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v)));
  return [name, ...values].join(" · ");
}

// Same mark as public/favicon.svg, drawn on a 16px grid so the bars stay crisp
function LogoMark() {
  return (
    <svg
      className="logo-mark"
      width="20"
      height="20"
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      <rect className="logo-bg" width="16" height="16" rx="3.5" />
      <g fill="#FFFFFF">
        <rect x="3" y="5" width="2" height="6" rx="1" />
        <rect x="7" y="3" width="2" height="10" rx="1" />
        <rect x="11" y="6" width="2" height="4" rx="1" />
      </g>
    </svg>
  );
}

// Day 2: the server keeps the history (LangGraph checkpointer).
// We send only the thread id and the new message.
async function sendChat(
  threadId: string,
  message: string,
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]); // display only
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // One conversation per page load. A ref keeps the same value across
  // renders without causing a re-render.
  const threadId = useRef(crypto.randomUUID());

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, pending, error]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || pending) return;

    const next: Message[] = [...messages, { role: "user", content }];
    setMessages(next);
    setInput("");
    setError(null);
    setPending(true);
    try {
      const data = await sendChat(threadId.current, content);
      setMessages([
        ...next,
        { role: "assistant", content: data.reply, toolCalls: data.tool_calls },
      ]);
    } catch {
      setError("Couldn’t reach Assist. Try again.");
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  const empty = messages.length === 0 && !pending && !error;

  return (
    <div className="app">
      <header className="column header">
        <LogoMark />
        <span>Assist</span>
      </header>

      <main className="scroll">
        <div
          className={`column thread${empty ? " is-empty" : ""}`}
          aria-live="polite"
        >
          {empty && (
            <div className="empty">
              <h1>What can I do for you?</h1>
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
            m.role === "user" ? (
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
            type="button"
            className="icon-btn mic"
            disabled
            aria-label="Voice input (coming soon)"
            title="Voice input (coming soon)"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="3" width="6" height="12" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
            </svg>
          </button>
          <button
            type="submit"
            className="icon-btn send"
            disabled={!input.trim() || pending}
            aria-label="Send"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}
