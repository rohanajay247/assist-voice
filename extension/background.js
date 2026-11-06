// Assist "Save my tabs" bridge.
// Keeps a WebSocket open to the Assist API and answers three commands:
//   list  -> every tab (id, title, url, pinned)
//   close -> close tabs by id
//   open  -> open http(s) links in the background
// Chrome keeps the service worker alive while the socket is busy, so a
// ping every 20 s holds it open; an alarm reconnects if Chrome stopped it.

const DEFAULTS = { apiUrl: "http://localhost:8000", token: "", enabled: true };
const ICONS = { 16: "icons/icon16.png", 32: "icons/icon32.png", 48: "icons/icon48.png" };
let socket = null;
let pingTimer = null;
let status = "disconnected";

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(["apiUrl", "token", "enabled"])) };
}

function setStatus(s) {
  status = s;
  chrome.action.setIcon({ path: ICONS });
  chrome.action.setBadgeText({ text: s === "connected" ? "" : s === "paused" ? "II" : "off" });
  chrome.action.setBadgeBackgroundColor({ color: "#a8453c" });
  chrome.action.setTitle({
    title: s === "connected" ? "Assist Voice · connected" : s === "paused" ? "Assist Voice · paused" : "Assist Voice · not connected",
  });
}

async function handle(msg) {
  if (msg.cmd === "list") {
    const tabs = await chrome.tabs.query({});
    return {
      tabs: tabs.map((t) => ({
        id: t.id, title: t.title || "", url: t.url || "", pinned: t.pinned,
        active: t.active, windowId: t.windowId,
      })),
    };
  }
  if (msg.cmd === "close") {
    const ids = (msg.ids || []).filter(Number.isInteger);
    if (ids.length) await chrome.tabs.remove(ids);
    return { closed: ids.length };
  }
  if (msg.cmd === "open") {
    const urls = (msg.urls || []).filter((u) => /^https?:\/\//.test(u));
    for (const url of urls) await chrome.tabs.create({ url, active: false });
    return { opened: urls.length };
  }
  return { error: `unknown command ${msg.cmd}` };
}

async function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const { apiUrl, token, enabled } = await settings();
  if (!enabled) return setStatus("paused"); // user disconnected: stay off until turned back on
  const url = apiUrl.replace(/^http/, "ws").replace(/\/$/, "") + "/ext/ws" +
    (token ? `?token=${encodeURIComponent(token)}` : "");
  setStatus("connecting");
  socket = new WebSocket(url);

  socket.onopen = () => {
    setStatus("connected");
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
    }, 20000);
  };
  socket.onmessage = async (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "pong" || !msg.id) return;
    let reply;
    try {
      reply = await handle(msg);
    } catch (e) {
      reply = { error: String(e?.message || e) };
    }
    socket?.send(JSON.stringify({ id: msg.id, ...reply }));
  };
  socket.onclose = async () => {
    clearInterval(pingTimer);
    socket = null;
    if (!(await settings()).enabled) return setStatus("paused");
    setStatus("disconnected");
    setTimeout(connect, 5000); // API restarted (--reload): try again soon
  };
  socket.onerror = () => {}; // onclose follows and handles it
}

chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.storage.onChanged.addListener(() => { socket?.close(); connect(); });
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "status") reply(status);
});
connect();
