// Job Agent background worker: talks to the website API and walks through the approved queue,
// one job (one tab) at a time.

const get = (keys) => chrome.storage.local.get(keys);
const set = (obj) => chrome.storage.local.set(obj);

async function api(path, opts = {}) {
  const { site, token } = await get(["site", "token"]);
  if (!site || !token) throw new Error("Open the extension and add your site URL and key first.");
  const res = await fetch(site.replace(/\/$/, "") + path, {
    ...opts,
    headers: { ...(opts.headers || {}), authorization: "Bearer " + token, "content-type": "application/json" },
  });
  if (!res.ok) throw new Error(`${path}: ${res.status} ${(await res.text()).slice(0, 200)}`);
  return res;
}

function applyUrl(job) {
  const j = job.jobs;
  let u = j.apply_url || j.url;
  // Land directly on the form.
  if (j.ats === "lever" && !/\/apply\/?$/.test(u)) u = u.replace(/\/?$/, "/apply");
  if (j.ats === "ashby" && !/\/application\/?$/.test(u)) u = u.replace(/\/?$/, "/application");
  return u;
}

async function resumeBase64(which) {
  const res = await api(`/api/ext/resume?which=${which}`);
  const name = decodeURIComponent(res.headers.get("x-file-name") || "resume.pdf");
  const buf = new Uint8Array(await res.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return { name, b64: btoa(bin) };
}

async function report(job_id, status, note) {
  try {
    await api("/api/ext/report", { method: "POST", body: JSON.stringify({ job_id, status, note }) });
  } catch (e) {
    console.warn("report failed", e);
  }
}

async function openNext() {
  const { queue = [], tabId } = await get(["queue", "tabId"]);
  if (tabId) chrome.tabs.remove(tabId).catch(() => {});
  if (queue.length === 0) {
    await set({ running: false, current: null, tabId: null, status: "Done: queue is empty." });
    return;
  }
  const [job, ...rest] = queue;
  await report(job.job_id, "applying");
  const tab = await chrome.tabs.create({ url: applyUrl(job), active: true });
  await set({ queue: rest, current: job, tabId: tab.id, status: `Filling ${job.jobs.company}: ${job.jobs.title}` });
}

async function start() {
  const res = await api("/api/ext/queue");
  const data = await res.json();
  if (data.daily_limit_reached) {
    await set({ status: "Daily limit reached. Change it in Settings on the site.", running: false });
    return;
  }
  const profileRes = await (await api("/api/ext/me")).json();
  if (!profileRes.has_resume) {
    await set({ status: "Upload a resume in Settings on the site first.", running: false });
    return;
  }
  await set({ queue: data.jobs, profile: profileRes.profile, running: true, done: [] });
  await openNext();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      if (msg.type === "start") { await start(); return reply({ ok: true }); }
      if (msg.type === "stop") { await set({ running: false, queue: [], current: null, status: "Stopped." }); return reply({ ok: true }); }
      if (msg.type === "context") {
        // A form page asks: am I the job we opened, and what should I fill?
        const { running, current, tabId, profile, autoSubmit } = await get(["running", "current", "tabId", "profile", "autoSubmit"]);
        if (!running || !current || sender.tab?.id !== tabId) return reply({ active: false });
        const resume = await resumeBase64(current.resume_choice === "alt" ? "alt" : "main");
        return reply({ active: true, job: current, profile, resume, autoSubmit: !!autoSubmit });
      }
      if (msg.type === "result") {
        const { current, done = [] } = await get(["current", "done"]);
        if (!current) return reply({ ok: false });
        await report(current.job_id, msg.status, msg.note);
        done.push({ company: current.jobs.company, title: current.jobs.title, status: msg.status, note: msg.note || "" });
        await set({ done, current: null });
        await openNext();
        return reply({ ok: true });
      }
      reply({ ok: false });
    } catch (e) {
      await set({ status: "Error: " + e.message });
      reply({ ok: false, error: e.message });
    }
  })();
  return true; // async reply
});

// If the user closes the job tab, put the job back as approved and move on.
chrome.tabs.onRemoved.addListener(async (closedId) => {
  const { tabId, current, running } = await get(["tabId", "current", "running"]);
  if (running && closedId === tabId && current) {
    await report(current.job_id, "approved", null);
    await set({ tabId: null, current: null, running: false, status: "Paused: you closed the tab. Press Start to continue." });
  }
});
