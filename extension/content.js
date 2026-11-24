// Runs on Greenhouse / Lever / Ashby pages. If this tab is the job the extension opened,
// fill the form, show a checklist panel, and report the outcome back.
/* global JobFiller */

(async () => {
  const ctx = await chrome.runtime.sendMessage({ type: "context" }).catch(() => null);
  if (!ctx?.active) return;

  let reported = false;
  const send = (status, note) => {
    if (reported) return;
    reported = true;
    chrome.runtime.sendMessage({ type: "result", status, note });
  };

  // Already on a confirmation page (e.g. after submit navigated here).
  if (JobFiller.isSuccessPage()) return send("applied");

  // Lever/Greenhouse sometimes land on the description; click through to the form.
  const applyLink = [...document.querySelectorAll("a, button")].find((a) => /^apply( for this job| now)?$/i.test(a.textContent.trim()));
  if (applyLink && !document.querySelector('input[type="file"]')) applyLink.click();

  // Wait for the form to render (these boards are React apps).
  for (let i = 0; i < 40 && !document.querySelector('input[type="file"], input[type="email"]'); i++) {
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!document.querySelector("input, textarea")) return send("needs_you", "Couldn't find the application form");

  const result = await JobFiller.fillForm(ctx);
  const captcha = JobFiller.hasCaptcha();
  panel(result, captcha);

  // Watch for the thank-you page after the user (or auto-submit) submits.
  const watcher = setInterval(() => {
    if (JobFiller.isSuccessPage()) { clearInterval(watcher); send("applied"); }
  }, 1000);

  const clean = result.resume && result.missing.length === 0 && result.review.length === 0 && !captcha;
  if (ctx.autoSubmit && clean) {
    await new Promise((r) => setTimeout(r, 1500));
    JobFiller.submitButton()?.click();
  }

  function panel(r, captcha) {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;width:340px;max-height:70vh;overflow:auto;" +
      "background:#fff;color:#1c1c1a;border:1px solid #ccc;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);" +
      "font:13px/1.4 system-ui,sans-serif;padding:12px";
    const list = (title, items, color) => items.length
      ? `<div style="margin-top:8px;color:${color};font-weight:600">${title} (${items.length})</div><ul style="margin:4px 0 0 16px;padding:0">${
          items.map((t) => `<li>${t.replace(/</g, "&lt;")}</li>`).join("")}</ul>` : "";
    host.innerHTML = `
      <div style="font-weight:700">Job Agent: ${ctx.job.jobs.company}</div>
      <div style="color:#6b6b66">${ctx.job.jobs.title}</div>
      <div style="margin-top:6px">${r.resume ? "✓ Resume attached" : "⚠ Couldn't attach resume"}</div>
      ${captcha ? '<div style="color:#a12c2c;margin-top:6px">⚠ CAPTCHA on this page: solve it yourself.</div>' : ""}
      ${list("Needs you", r.missing, "#a12c2c")}
      ${list("Check before submitting", r.review, "#9a5b00")}
      ${list("Left blank on purpose", r.skipped, "#6b6b66")}
      ${list("Filled", r.filled, "#1f6f3f")}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
        <button data-a="submitted" style="padding:6px 10px;border-radius:6px;border:1px solid #1f5f4a;background:#1f5f4a;color:#fff;font-weight:600">I submitted it</button>
        <button data-a="later" style="padding:6px 10px;border-radius:6px;border:1px solid #9a5b00;background:#fff;color:#9a5b00">Do later</button>
        <button data-a="skip" style="padding:6px 10px;border-radius:6px;border:1px solid #999;background:#fff;color:#444">Skip job</button>
      </div>`;
    host.addEventListener("click", (e) => {
      const a = e.target?.dataset?.a;
      if (a === "submitted") send("applied");
      if (a === "later") send("needs_you", r.missing.length ? "Unanswered: " + r.missing.slice(0, 3).join("; ") : "Saved for later");
      if (a === "skip") send("skipped", "Skipped in extension");
    });
    document.body.appendChild(host);
  }
})();
