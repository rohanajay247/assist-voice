import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

type Role = "user" | "assistant";

interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  preview?: ToolPreviewData | null; // extra detail for the approval card
}

// What install_tool / build_tool show on the approval card (see preview_of in agent.py)
interface ToolPreviewData {
  kind: "tool" | "build";
  name: string;
  description: string;
  network: boolean;
  tools?: { name: string; description: string }[];
  passed?: number;
  total?: number;
  tests?: { call: string; output: string; ok: boolean }[];
  code?: string;
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
  image?: string; // data URL of a photo the user sent
  toolCalls?: ToolCall[];
  steps?: Step[];
}

interface ChatResponse {
  reply: string;
  tool_calls: ToolCall[];
  pending?: ToolCall[] | null; // calls waiting for the user's OK
  steps?: Step[];
}

// --- API -------------------------------------------------------------------

// Paths are relative: Vite proxies /chat, /approve and /transcribe to the
// backend, so the app works the same on localhost and through the tunnel.
const TOKEN_KEY = "assist.token";

function loadToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the token works for this request only
  }
}

class UnauthorizedError extends Error {}

const TOKEN_EXPIRED = "Your access token stopped working. Enter it again.";

function tokenHeaders(token: string, init?: HeadersInit): Headers {
  const headers = new Headers(init);
  if (token) headers.set("X-Assist-Token", token);
  return headers;
}

// Asks the backend whether this token is accepted. "offline" means the
// server couldn't be reached (or isn't Assist), which is not a lock reason.
async function checkToken(token: string): Promise<"ok" | "denied" | "offline"> {
  try {
    const res = await fetch("/auth/check", { headers: tokenHeaders(token) });
    if (res.status === 401) return "denied";
    return res.ok ? "ok" : "offline";
  } catch {
    return "offline";
  }
}

// Sends the saved access token. A 401 means it stopped working: forget it
// and let the caller show the lock view.
async function apiFetch(path: string, init: RequestInit): Promise<Response> {
  const res = await fetch(path, {
    ...init,
    headers: tokenHeaders(loadToken(), init.headers),
  });
  if (res.status === 401) {
    saveToken("");
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

const EXAMPLES = [
  "What’s the weather tomorrow?",
  "Note that I need milk",
  "What notes do I have?",
];

// "get_weather · Albstadt · days 2": tool name, then its arguments.
// Strings read fine alone; other values get their key so "2" means something.
// Args left out of the short label (still in the chip's title): an email body and
// Gmail's raw message id say little in a one-line chip
const LABEL_HIDDEN = new Set(["body", "reply_to_message_id"]);

// Long values are cut to one short line; the chip's title has the full text.
function formatToolCall({ name, args }: ToolCall, maxValue = 48): string {
  const clip = (s: string) => {
    const line = s.replace(/\s+/g, " ").trim();
    return line.length > maxValue
      ? `${line.slice(0, maxValue - 1).trimEnd()}…`
      : line;
  };
  const parts = Object.entries(args)
    .filter(([k]) => maxValue > 100 || !LABEL_HIDDEN.has(k))
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) =>
      typeof v === "string"
        ? clip(v)
        : `${k} ${clip(typeof v === "object" ? JSON.stringify(v) : String(v))}`,
    );
  return [name, ...parts].join(" · ");
}

// What a create_draft call will put in Gmail, laid out like an email
function EmailPreview({ args }: { args: Record<string, unknown> }) {
  const field = (key: string) =>
    typeof args[key] === "string" ? (args[key] as string) : "";
  // Gemini sometimes sends literal "\n"; the server turns those into line breaks too
  const body = field("body").replace(/\\n/g, "\n").trim();
  return (
    <div className="email-preview">
      <div className="email-label">Draft email · not sent</div>
      <div className="email-meta">
        <span className="email-key">To</span>
        <span className="email-value">{field("to")}</span>
      </div>
      <div className="email-meta">
        <span className="email-key">Subject</span>
        <span className="email-value">
          {field("subject") || "(no subject)"}
        </span>
      </div>
      {field("reply_to_message_id") && (
        <div className="email-meta">
          <span className="email-key">Thread</span>
          <span className="email-value">
            Reply in the existing conversation
          </span>
        </div>
      )}
      <div className="email-body">{body}</div>
    </div>
  );
}

// A tool Assist built: what it does, its test results and the code, before it's added
function ToolPreview({ preview }: { preview: ToolPreviewData }) {
  if (preview.kind === "build") {
    return (
      <div className="email-preview">
        <div className="email-label">Build a tool · with internet access</div>
        <div className="email-meta">
          <span className="email-key">Name</span>
          <span className="email-value">{preview.name}</span>
        </div>
        <div className="email-body">{preview.description}</div>
      </div>
    );
  }
  const allPassed = preview.passed === preview.total && (preview.total ?? 0) > 0;
  return (
    <div className="email-preview">
      <div className="email-label">
        New tool · runs in the sandbox ·{" "}
        {preview.network ? "internet access, asks before each use" : "no internet"}
      </div>
      <div className="email-meta">
        <span className="email-key">Name</span>
        <span className="email-value">{preview.name}</span>
      </div>
      <div className="email-meta">
        <span className="email-key">Tools</span>
        <span className="email-value">
          {(preview.tools ?? []).map((t) => t.name).join(", ")}
        </span>
      </div>
      <div className="email-meta">
        <span className="email-key">Tests</span>
        <span className={allPassed ? "email-value test-ok" : "email-value test-fail"}>
          {preview.passed}/{preview.total} passed
        </span>
      </div>
      <ul className="tool-tests">
        {(preview.tests ?? []).map((t, i) => (
          <li key={i} className={t.ok ? "test-ok" : "test-fail"}>
            {t.ok ? "✓" : "✗"} {t.call} → {t.output}
          </li>
        ))}
      </ul>
      <details className="tool-code">
        <summary>Show code</summary>
        <pre>{preview.code}</pre>
      </details>
    </div>
  );
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
  // A draft is described by who it's for, not read out in full
  if (name === "create_draft") {
    const subject =
      typeof args.subject === "string" && args.subject
        ? ` about "${args.subject}"`
        : "";
    return `Create a draft email to ${String(args.to ?? "someone")}${subject}. It won't be sent.`;
  }
  if (name === "install_tool" && args && "proposal_id" in args) {
    return "Add a new tool I built. Its tests and code are on screen.";
  }
  if (name === "build_tool") {
    return `Build a tool called ${String(args.name ?? "")} that can use the internet.`;
  }
  const action = name.replace(/_/g, " ");
  const details = Object.values(args).filter(
    (v): v is string => typeof v === "string" && v !== "",
  );
  const sentence = details.length ? `${action}: ${details.join(", ")}` : action;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
}

// Rough guess so German replies get a German voice when one is installed
// Common words of each language. Counting them (instead of looking for ä/ö/ü)
// keeps an English reply English when it quotes a German name or letter.
const DE_WORDS = new Set(
  "und ist nicht das ich der den dem des ein eine einen sie wir mit für auf von zu bitte heute morgen wetter ja nein es du bei oder aber wird sind haben".split(" "),
);
const EN_WORDS = new Set(
  "the and is are to you your of it this that by for with what on in be will a an i can it's there".split(" "),
);

function guessLang(text: string): string {
  let de = 0;
  let en = 0;
  for (const word of text.toLowerCase().match(/[\p{L}']+/gu) ?? []) {
    if (DE_WORDS.has(word)) de++;
    if (EN_WORDS.has(word)) en++;
  }
  return de > en ? "de-DE" : "en-US"; // a tie stays English
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

// The prompt asks for plain text, but Gemini sometimes still adds ** or #
function stripMarkdown(text: string): string {
  return text.replace(/\*\*|__|`/g, "").replace(/^\s*#+\s*/gm, "");
}

function speak(text: string, voiceURI = "") {
  if (!("speechSynthesis" in window) || !text.trim()) return;
  window.speechSynthesis.cancel(); // never queue up behind an old reply
  // Lists read better without their dashes
  const spoken = stripMarkdown(text).replace(/^\s*[-*•]\s+/gm, "");
  const utterance = new SpeechSynthesisUtterance(spoken);
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
  const res = await apiFetch("/transcribe", { method: "POST", body: form });
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
function LogoMark({ size = 20 }: { size?: number }) {
  return (
    <svg
      className="logo-mark"
      width={size}
      height={size}
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

// Shown instead of the chat until the access token is accepted
function LockView({
  message,
  onUnlock,
}: {
  message: string | null;
  onUnlock: (token: string) => Promise<string | null>;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = token.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    const problem = await onUnlock(value);
    // On success the app swaps this view out; only update state on failure
    if (problem) {
      setBusy(false);
      setError(problem);
    }
  }

  const shown = error ?? message;
  return (
    <div className="lock">
      <form className="lock-card" onSubmit={submit}>
        <LogoMark size={40} />
        <h1>Assist</h1>
        <p className="lock-hint">Enter your access token to continue.</p>
        <input
          className="lock-input"
          type="password"
          name="token"
          autoComplete="current-password"
          placeholder="Access token"
          aria-label="Access token"
          aria-invalid={!!error}
          aria-describedby="lock-error"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoFocus
        />
        <button
          className="lock-button"
          type="submit"
          disabled={!token.trim() || busy}
        >
          {busy ? "Checking…" : "Unlock"}
        </button>
        <p
          id="lock-error"
          className={`lock-error${error ? " is-error" : ""}`}
          role="alert"
        >
          {shown}
        </p>
      </form>
    </div>
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

// --- Photos -----------------------------------------------------------------

const MAX_IMAGE_SIDE = 1600; // px; enough to read a letter, small to upload
const IMAGE_QUALITY = 0.8;

// Shrink a photo or screenshot and re-encode it as JPEG, returned as a data URL.
// Phone photos are 3-10 MB; this brings them to a few hundred KB.
async function resizeImage(file: Blob): Promise<string> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no canvas");
  ctx.fillStyle = "#ffffff"; // transparent PNGs get a white background, not black
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", IMAGE_QUALITY);
}

// The server keeps the history (LangGraph checkpointer).
// /chat sends a new message, /approve answers a pending approval.
async function post(path: string, body: unknown): Promise<ChatResponse> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]); // display only
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string | null>(null); // photo waiting to be sent
  const fileRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState(false); // request in flight
  const [approval, setApproval] = useState<ToolCall[] | null>(null); // waiting for OK
  const [approvalSteps, setApprovalSteps] = useState<Step[]>([]); // steps so far
  const [error, setError] = useState<string | null>(null);
  const [voice, setVoice] = useState<
    "idle" | "starting" | "recording" | "transcribing"
  >("idle");
  // "checking" until /auth/check answers; "locked" shows the lock view
  const [auth, setAuth] = useState<"checking" | "locked" | "open">("checking");
  const [lockMessage, setLockMessage] = useState<string | null>(null);
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

  // On open: is the saved token (or no token) accepted?
  useEffect(() => {
    const saved = loadToken();
    checkToken(saved).then((result) => {
      if (result === "denied") {
        saveToken("");
        setLockMessage(saved ? TOKEN_EXPIRED : null);
        setAuth("locked");
      } else {
        setAuth("open"); // "offline" too: sending then shows the usual error
      }
    });
  }, []);

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

  // A call came back 401: back to the lock view (the chat stays in memory)
  function lock(message: string | null) {
    stopSpeaking();
    setLockMessage(message);
    setAuth("locked");
  }

  async function run(request: () => Promise<ChatResponse>) {
    setError(null);
    setPending(true);
    try {
      show(await request());
    } catch (e) {
      if (e instanceof UnauthorizedError) lock(TOKEN_EXPIRED);
      else setError("Couldn’t reach Assist. Try again.");
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function send(text: string) {
    const content = text.trim();
    const photo = image;
    // While an approval is open, the graph is paused: answer it first
    if ((!content && !photo) || pending || approval) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content, ...(photo ? { image: photo } : {}) },
    ]);
    setInput("");
    setImage(null);
    // An empty message with a photo: the server asks a default question
    run(() =>
      post("/chat", {
        thread_id: threadId.current,
        message: content,
        ...(photo ? { image: photo } : {}),
      }),
    );
  }

  async function attach(file: Blob | null | undefined) {
    if (!file || !file.type.startsWith("image/")) return;
    try {
      setImage(await resizeImage(file));
      setError(null);
    } catch {
      setError("Couldn’t read that image. Try another one.");
    }
    inputRef.current?.focus();
  }

  function onPickPhoto(e: ChangeEvent<HTMLInputElement>) {
    attach(e.target.files?.[0]);
    e.target.value = ""; // picking the same file again still fires onChange
  }

  // Ctrl+V of a screenshot into the text box attaches it
  function onPaste(e: ClipboardEvent<HTMLInputElement>) {
    const item = Array.from(e.clipboardData.items).find((i) =>
      i.type.startsWith("image/"),
    );
    if (!item) return; // plain text: normal paste
    e.preventDefault();
    attach(item.getAsFile());
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
    } catch (e) {
      setVoice("idle");
      if (e instanceof UnauthorizedError) lock(TOKEN_EXPIRED);
      else setError("Couldn’t transcribe that. Try again.");
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

  // Returns an error message for the lock view, or null once unlocked
  async function unlock(token: string): Promise<string | null> {
    const result = await checkToken(token);
    if (result === "denied")
      return "That token didn’t work. Check it and try again.";
    if (result === "offline")
      return "Couldn’t reach Assist. Is the server running?";
    saveToken(token);
    setLockMessage(null);
    setAuth("open");
    return null;
  }

  if (auth === "checking") return <div className="app" />;
  if (auth === "locked")
    return <LockView message={lockMessage} onUnlock={unlock} />;

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
                {m.image && (
                  <img className="msg-photo" src={m.image} alt="Photo you sent" />
                )}
                {m.content}
              </div>
            ) : (
              <div key={i} className="msg-assistant">
                {stripMarkdown(m.content)}
                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="tools">
                    {m.toolCalls.map((tc, j) => (
                      <span
                        key={j}
                        className="tool"
                        title={formatToolCall(tc, 2000)}
                      >
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
              {approval.map((tc, j) =>
                tc.name === "create_draft" ? (
                  <EmailPreview key={j} args={tc.args} />
                ) : tc.preview ? (
                  <ToolPreview key={j} preview={tc.preview} />
                ) : (
                  <div key={j} className="tools">
                    <span className="tool" title={formatToolCall(tc, 2000)}>
                      {formatToolCall(tc)}
                    </span>
                  </div>
                ),
              )}
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
        {image && (
          <div className="attachment">
            <img src={image} alt="Photo to send" />
            <button
              type="button"
              className="attachment-remove"
              onClick={() => setImage(null)}
              aria-label="Remove photo"
              title="Remove photo"
            >
              ×
            </button>
          </div>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={onPickPhoto}
        />
        <div className="field">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={onPaste}
            placeholder={placeholder}
            aria-label="Message"
            disabled={!!approval}
            autoFocus
          />
          <button
            type="button"
            className="icon-btn camera"
            disabled={pending || !!approval}
            onClick={() => fileRef.current?.click()}
            aria-label="Add a photo"
            title="Add a photo (or paste a screenshot)"
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
              <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
              <circle cx="12" cy="13" r="3.5" />
            </svg>
          </button>
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
            disabled={(!input.trim() && !image) || pending || !!approval}
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
