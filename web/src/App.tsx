import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

type Role = "user" | "assistant";

interface ToolCall {
  name: string;
  args: Record<string, unknown>;
}

// One line in the step panel, built by the server from this turn's messages
interface Step {
  kind: "plan" | "approval" | "tool" | "undo_log";
  label: string;
  status: "ok" | "denied" | "error" | "waiting";
}

interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
  steps?: Step[];
}

interface ChatResponse {
  reply: string;
  tool_calls: ToolCall[];
  pending?: ToolCall[] | null; // calls waiting for the user's OK
  steps?: Step[];
}

const API_URL = import.meta.env.VITE_API_URL as string;

const EXAMPLES = [
  "What’s the weather tomorrow?",
  "Note that I need milk",
  "What notes do I have?",
];

// "get_weather · Albstadt · days 2": tool name, then its arguments.
// Strings read fine alone; other values get their key so "2" means something.
function formatToolCall({ name, args }: ToolCall): string {
  const parts = Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) =>
      typeof v === "string"
        ? v
        : `${k} ${typeof v === "object" ? JSON.stringify(v) : String(v)}`,
    );
  return [name, ...parts].join(" · ");
}

// --- Voice -----------------------------------------------------------------

const MIN_RECORDING_MS = 300; // shorter presses are treated as accidental taps
const MUTE_KEY = "assist.muted";
const VOICE_KEY = "assist.voice"; // voiceURI, or "" for automatic

const YES_WORDS = ["yes", "yeah", "okay", "ok", "sure", "ja", "do it"];
const NO_WORDS = ["no", "nope", "cancel", "nein", "stop"];

// Whisper returns "Yes." or "Okay, do it!", so compare lowercase words only.
// A phrase counts if it is, or starts with, one of the words ("yes please").
function matchYesNo(transcript: string): "yes" | "no" | null {
  const text = transcript
    .toLowerCase()
    .replace(/[^\p{L}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  const hit = (words: string[]) =>
    words.some((w) => text === w || text.startsWith(w + " "));
  if (hit(NO_WORDS)) return "no";
  if (hit(YES_WORDS)) return "yes";
  return null;
}

// "add_note {text: 'Buy milk'}" -> "Add note: Buy milk."
function describeCall({ name, args }: ToolCall): string {
  const action = name.replace(/_/g, " ");
  const details = Object.values(args).filter(
    (v): v is string => typeof v === "string" && v !== "",
  );
  const sentence = details.length ? `${action}: ${details.join(", ")}` : action;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
}

// Rough guess so German replies get a German voice when one is installed
function guessLang(text: string): string {
  return /[äöüß]|\b(und|ist|nicht|das|ich|der|die|morgen|wetter)\b/i.test(text)
    ? "de-DE"
    : "en-US";
}

// Prefer the neural voices browsers ship: Edge "… Online (Natural)", Chrome "Google …"
function voiceScore(v: SpeechSynthesisVoice): number {
  return (
    (/natural/i.test(v.name) ? 4 : 0) +
    (/online|google/i.test(v.name) ? 2 : 0) +
    (v.default ? 1 : 0)
  );
}

// The chosen voice if it speaks this language, otherwise the best one that does
function pickVoice(
  lang: string,
  chosenURI: string,
): SpeechSynthesisVoice | undefined {
  const prefix = lang.slice(0, 2);
  const voices = window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang.toLowerCase().startsWith(prefix));
  return (
    voices.find((v) => v.voiceURI === chosenURI) ??
    voices.sort((a, b) => voiceScore(b) - voiceScore(a))[0]
  );
}

// "Microsoft Aria Online (Natural) - English (United States)" -> "Aria (Natural) · en-US"
function voiceLabel(v: SpeechSynthesisVoice): string {
  const name = v.name
    .replace(/^Microsoft /, "")
    .replace(/ Online \(Natural\)/, " (Natural)")
    .replace(/ - .*$/, "");
  return `${name} · ${v.lang}`;
}

function speak(text: string, voiceURI = "") {
  if (!("speechSynthesis" in window) || !text.trim()) return;
  window.speechSynthesis.cancel(); // never queue up behind an old reply
  const utterance = new SpeechSynthesisUtterance(text);
  const lang = guessLang(text);
  const voice = pickVoice(lang, voiceURI);
  utterance.lang = voice?.lang ?? lang;
  if (voice) utterance.voice = voice;
  window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

// localStorage can throw (private mode, blocked storage), so it is best effort
function loadPref(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore: the setting still works for this page load
  }
}

// First format this browser can record; Groq reads the format from the extension
function pickMimeType(): string {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  return types.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

function extensionFor(mimeType: string): string {
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("mp4")) return "mp4";
  return "webm";
}

async function transcribe(audio: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", audio, `speech.${extensionFor(audio.type)}`);
  const res = await fetch(`${API_URL}/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data: { text: string } = await res.json();
  return data.text;
}

function micError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access is blocked. Allow it in your browser settings to talk.";
  if (name === "NotFoundError") return "No microphone found.";
  return "Couldn’t start the microphone.";
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

const STEP_ICONS: Record<Step["status"], string> = {
  ok: "✓",
  denied: "✕",
  error: "!",
  waiting: "◌",
};

const STEP_STATUS_TEXT: Record<Step["status"], string> = {
  ok: "done",
  denied: "denied",
  error: "failed",
  waiting: "waiting",
};

// "Steps (n)" under a reply: what Assist did, collapsed unless asked
function Steps({
  steps,
  defaultOpen = false,
}: {
  steps: Step[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="steps">
      <button
        type="button"
        className="steps-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <svg
          className="steps-chevron"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m9 6 6 6-6 6" />
        </svg>
        Steps ({steps.length})
      </button>
      {open && (
        <ol className="steps-list">
          {steps.map((s, i) => (
            <li key={i} className={`step step-${s.status}`}>
              <span className="step-icon" aria-hidden="true">
                {STEP_ICONS[s.status]}
              </span>
              <span className="step-label">{s.label}</span>
              <span className="visually-hidden">
                , {STEP_STATUS_TEXT[s.status]}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// Voice picker: a small popover instead of a native <select>, whose open
// list can't be themed (it stays white in dark mode).
function VoiceMenu({
  voices,
  value,
  onChange,
}: {
  voices: SpeechSynthesisVoice[];
  value: string;
  onChange: (uri: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Best-sounding voices first within each language
  const byScore = (a: SpeechSynthesisVoice, b: SpeechSynthesisVoice) =>
    voiceScore(b) - voiceScore(a);
  const groups = [
    {
      label: "English",
      voices: voices.filter((v) => /^en/i.test(v.lang)).sort(byScore),
    },
    {
      label: "Deutsch",
      voices: voices.filter((v) => /^de/i.test(v.lang)).sort(byScore),
    },
  ].filter((g) => g.voices.length > 0);

  const current = voices.find((v) => v.voiceURI === value);
  const currentLabel = current ? voiceLabel(current) : "Auto voice";

  // While open: close on outside press, and start keyboard focus on the selection
  useEffect(() => {
    if (!open) return;
    const items =
      listRef.current?.querySelectorAll<HTMLElement>('[role="option"]');
    const selected = listRef.current?.querySelector<HTMLElement>(
      '[aria-selected="true"]',
    );
    (selected ?? items?.[0])?.focus();

    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function pick(uri: string) {
    setOpen(false);
    buttonRef.current?.focus();
    onChange(uri);
  }

  function onListKeyDown(e: KeyboardEvent) {
    const items = [
      ...(listRef.current?.querySelectorAll<HTMLElement>('[role="option"]') ??
        []),
    ];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(i + step + items.length) % items.length]?.focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      items[e.key === "Home" ? 0 : items.length - 1]?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  const option = (uri: string, label: string) => (
    <div
      key={uri || "auto"}
      role="option"
      tabIndex={-1}
      aria-selected={uri === value}
      className="voice-option"
      onClick={() => pick(uri)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          pick(uri);
        }
      }}
    >
      <span className="voice-option-label">{label}</span>
      {uri === value && (
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.25"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      )}
    </div>
  );

  return (
    <div className="voice-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="voice-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Voice for spoken replies: ${currentLabel}`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="voice-trigger-label">{currentLabel}</span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div
          ref={listRef}
          className="voice-list"
          role="listbox"
          aria-label="Voice for spoken replies"
          onKeyDown={onListKeyDown}
        >
          {option("", "Auto voice")}
          {groups.map((g) => (
            <div key={g.label} role="group" aria-label={g.label}>
              <div className="voice-group" aria-hidden="true">
                {g.label}
              </div>
              {g.voices.map((v) => option(v.voiceURI, voiceLabel(v)))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// The server keeps the history (LangGraph checkpointer).
// /chat sends a new message, /approve answers a pending approval.
async function post(path: string, body: unknown): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]); // display only
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false); // request in flight
  const [approval, setApproval] = useState<ToolCall[] | null>(null); // waiting for OK
  const [approvalSteps, setApprovalSteps] = useState<Step[]>([]); // steps so far
  const [error, setError] = useState<string | null>(null);
  const [voice, setVoice] = useState<
    "idle" | "starting" | "recording" | "transcribing"
  >("idle");
  const [muted, setMuted] = useState(() => loadPref(MUTE_KEY) === "1");
  const [voiceURI, setVoiceURI] = useState(() => loadPref(VOICE_KEY) ?? "");
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // One conversation per page load. A ref keeps the same value across
  // renders without causing a re-render.
  const threadId = useRef(crypto.randomUUID());
  const recorderRef = useRef<MediaRecorder | null>(null);
  const holdingRef = useRef(false); // mic button still held down
  const startedAtRef = useRef(0);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, pending, error, approval]);

  // Browsers load their voice list late, so listen for it to arrive
  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const update = () =>
      setVoices(
        window.speechSynthesis
          .getVoices()
          .filter((v) => /^(en|de)/i.test(v.lang)),
      );
    update();
    window.speechSynthesis.addEventListener("voiceschanged", update);
    return () =>
      window.speechSynthesis.removeEventListener("voiceschanged", update);
  }, []);

  // Either the graph paused for approval, or it finished with a reply
  function show(data: ChatResponse) {
    // Read through the ref: the request may have started before a mute toggle
    const { muted: quiet, voiceURI: voice } = latest.current;
    if (data.pending && data.pending.length > 0) {
      setApproval(data.pending);
      setApprovalSteps(data.steps ?? []);
      if (!quiet)
        speak(
          `Okay to do this? ${data.pending.map(describeCall).join(" ")}`,
          voice,
        );
      return;
    }
    setApproval(null);
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: data.reply,
        toolCalls: data.tool_calls,
        steps: data.steps,
      },
    ]);
    if (!quiet) speak(data.reply, voice);
  }

  async function run(request: () => Promise<ChatResponse>) {
    setError(null);
    setPending(true);
    try {
      show(await request());
    } catch {
      setError("Couldn’t reach Assist. Try again.");
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function send(text: string) {
    const content = text.trim();
    // While an approval is open, the graph is paused: answer it first
    if (!content || pending || approval) return;
    setMessages((prev) => [...prev, { role: "user", content }]);
    setInput("");
    run(() => post("/chat", { thread_id: threadId.current, message: content }));
  }

  function decide(approved: boolean) {
    if (pending) return;
    run(() => post("/approve", { thread_id: threadId.current, approved }));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  // A recording finishes in callbacks created on an earlier render, so they
  // reach the current state and handlers through this ref.
  const latest = useRef({ approval, muted, voiceURI, send, decide });
  useEffect(() => {
    latest.current = { approval, muted, voiceURI, send, decide };
  });

  function toggleMuted() {
    const next = !muted;
    setMuted(next);
    savePref(MUTE_KEY, next ? "1" : "0");
    if (next) stopSpeaking();
  }

  // Save the pick and play a short sample so the change is audible right away
  function chooseVoice(uri: string) {
    setVoiceURI(uri);
    savePref(VOICE_KEY, uri);
    if (muted) return;
    const voice = voices.find((v) => v.voiceURI === uri);
    const german = voice?.lang.toLowerCase().startsWith("de");
    speak(german ? "Hallo, ich bin Assist." : "Hi, I'm Assist.", uri);
  }

  // Hold to talk: press starts recording, release stops it and transcribes
  async function startRecording() {
    if (voice !== "idle" || pending) return;
    holdingRef.current = true;
    stopSpeaking();
    setError(null);
    setVoice("starting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setVoice("idle");
      setError(micError(e));
      return;
    }
    // Released while the browser was still opening the mic (or asking permission)
    if (!holdingRef.current) {
      stream.getTracks().forEach((t) => t.stop());
      setVoice("idle");
      return;
    }

    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined,
    );
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstart = (e) => {
      startedAtRef.current = e.timeStamp;
    };
    recorder.onstop = (e) => {
      stream.getTracks().forEach((t) => t.stop()); // turn off the mic indicator
      const duration = e.timeStamp - startedAtRef.current;
      const blob = new Blob(chunks, {
        type: recorder.mimeType || "audio/webm",
      });
      if (duration < MIN_RECORDING_MS || blob.size === 0) {
        setVoice("idle");
        return;
      }
      handleRecording(blob);
    };
    recorderRef.current = recorder;
    recorder.start();
    setVoice("recording");
  }

  function stopRecording() {
    holdingRef.current = false;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    recorderRef.current = null;
  }

  async function handleRecording(blob: Blob) {
    setVoice("transcribing");
    let text: string;
    try {
      text = (await transcribe(blob)).trim();
    } catch {
      setVoice("idle");
      setError("Couldn’t transcribe that. Try again.");
      return;
    }
    setVoice("idle");
    if (!text) {
      setError("Didn’t catch that. Try again.");
      return;
    }

    const { approval, send, decide } = latest.current;
    // While an approval is open, the spoken answer goes to the card
    if (approval) {
      const answer = matchYesNo(text);
      if (answer) decide(answer === "yes");
      else setError("Say yes or no");
      return;
    }
    send(text);
  }

  const empty = messages.length === 0 && !pending && !error;
  const holdKey = (key: string) => key === " " || key === "Enter";
  const placeholder =
    voice === "recording" || voice === "starting"
      ? "Listening…"
      : voice === "transcribing"
        ? "Transcribing…"
        : approval
          ? "Approve or deny first"
          : "Message Assist";

  return (
    <div className="app">
      <header className="column header">
        <LogoMark />
        <span>Assist</span>
        <div className="header-actions">
          {voices.length > 0 && (
            <VoiceMenu
              voices={voices}
              value={voiceURI}
              onChange={chooseVoice}
            />
          )}
          <button
            type="button"
            className="icon-btn speaker"
            onClick={toggleMuted}
            aria-pressed={!muted}
            aria-label={
              muted ? "Read replies aloud" : "Stop reading replies aloud"
            }
            title={muted ? "Spoken replies off" : "Spoken replies on"}
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
              <path d="M11 5 6 9H3v6h3l5 4V5z" />
              {muted ? (
                <path d="m16 9 5 6M21 9l-5 6" />
              ) : (
                <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
              )}
            </svg>
          </button>
        </div>
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
                {m.steps && m.steps.length > 0 && <Steps steps={m.steps} />}
              </div>
            ),
          )}

          {approval && (
            <div className="msg-assistant">
              Okay to do this?
              <div className="tools">
                {approval.map((tc, j) => (
                  <span key={j} className="tool">
                    {formatToolCall(tc)}
                  </span>
                ))}
              </div>
              {approvalSteps.length > 0 && (
                <Steps steps={approvalSteps} defaultOpen />
              )}
              <div className="approval-actions">
                <button
                  className="btn btn-approve"
                  disabled={pending}
                  onClick={() => decide(true)}
                >
                  Approve
                </button>
                <button
                  className="btn btn-deny"
                  disabled={pending}
                  onClick={() => decide(false)}
                >
                  Deny
                </button>
              </div>
            </div>
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
            placeholder={placeholder}
            aria-label="Message"
            disabled={!!approval}
            autoFocus
          />
          <button
            type="button"
            className={`icon-btn mic${voice === "recording" ? " is-recording" : ""}${
              voice === "transcribing" ? " is-transcribing" : ""
            }`}
            disabled={pending || voice === "transcribing"}
            aria-label="Hold to talk"
            aria-pressed={voice === "recording"}
            title="Hold to talk"
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              e.preventDefault();
              // Keep getting pointerup even if the finger slides off the button
              try {
                e.currentTarget.setPointerCapture(e.pointerId);
              } catch {
                // capture is a nicety; recording still works without it
              }
              startRecording();
            }}
            onPointerUp={stopRecording}
            onPointerCancel={stopRecording}
            onContextMenu={(e) => e.preventDefault()} // no long-press menu on mobile
            onKeyDown={(e) => {
              if (holdKey(e.key) && !e.repeat) {
                e.preventDefault();
                startRecording();
              }
            }}
            onKeyUp={(e) => {
              if (holdKey(e.key)) {
                e.preventDefault();
                stopRecording();
              }
            }}
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
            disabled={!input.trim() || pending || !!approval}
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
