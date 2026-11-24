const $ = (id) => document.getElementById(id);

async function render() {
  const s = await chrome.storage.local.get(["site", "token", "autoSubmit", "status", "done", "queue"]);
  $("site").value = s.site || "";
  $("token").value = s.token || "";
  $("autoSubmit").checked = !!s.autoSubmit;
  $("status").textContent = (s.status || "Ready.") + (s.queue?.length ? ` (${s.queue.length} more queued)` : "");
  $("done").innerHTML = "";
  (s.done || []).slice(-10).forEach((d) => {
    const li = document.createElement("li");
    li.textContent = `${d.status === "applied" ? "✓" : "•"} ${d.company}: ${d.title}${d.note ? ` (${d.note})` : ""}`;
    $("done").appendChild(li);
  });
}

$("save").onclick = async () => {
  const site = $("site").value.trim().replace(/\/$/, "");
  try {
    const origin = new URL(site).origin + "/*";
    await chrome.permissions.request({ origins: [origin] }); // custom domains need this
  } catch { /* bad URL: saved anyway, start() will report the error */ }
  await chrome.storage.local.set({ site, token: $("token").value.trim(), autoSubmit: $("autoSubmit").checked });
  render();
};
$("start").onclick = async () => { await chrome.runtime.sendMessage({ type: "start" }); render(); };
$("stop").onclick = async () => { await chrome.runtime.sendMessage({ type: "stop" }); render(); };
chrome.storage.onChanged.addListener(render);
render();
