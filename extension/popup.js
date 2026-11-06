const $ = (id) => document.getElementById(id);
const LABELS = {
  connected: "Connected to Assist Voice",
  connecting: "Connecting…",
  disconnected: "API not reachable",
  paused: "Disconnected",
};

async function showStatus() {
  const s = await chrome.runtime.sendMessage("status").catch(() => "disconnected");
  $("statusText").textContent = LABELS[s] || s;
  $("status").className = "status " + ({ connected: "ok", paused: "paused", disconnected: "off" }[s] || "");
  if (s === "disconnected" && !$("token").value) $("settings").open = true; // first run: show settings
}

chrome.storage.local.get(["apiUrl", "token", "enabled"]).then(({ apiUrl, token, enabled }) => {
  $("apiUrl").value = apiUrl || "http://localhost:8000";
  $("token").value = token || "";
  $("enabled").checked = enabled !== false;
  showStatus();
});

// The switch: off closes the connection and stops reconnecting until it's turned back on
$("enabled").onchange = async () => {
  await chrome.storage.local.set({ enabled: $("enabled").checked });
  setTimeout(showStatus, 500);
};

$("save").onclick = async () => {
  await chrome.storage.local.set({ apiUrl: $("apiUrl").value.trim(), token: $("token").value.trim() });
  $("save").textContent = "Saved";
  setTimeout(() => ($("save").textContent = "Save"), 1200);
  setTimeout(showStatus, 1000);
};

setInterval(showStatus, 2000);
