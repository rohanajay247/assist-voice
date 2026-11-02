const $ = (id) => document.getElementById(id);

async function showStatus() {
  const s = await chrome.runtime.sendMessage("status").catch(() => "disconnected");
  $("status").textContent = s;
  $("status").className = s === "connected" ? "ok" : "off";
}

chrome.storage.local.get(["apiUrl", "token"]).then(({ apiUrl, token }) => {
  $("apiUrl").value = apiUrl || "http://localhost:8000";
  $("token").value = token || "";
});

$("save").onclick = async () => {
  await chrome.storage.local.set({ apiUrl: $("apiUrl").value.trim(), token: $("token").value.trim() });
  setTimeout(showStatus, 1000);
};

showStatus();
setInterval(showStatus, 2000);
