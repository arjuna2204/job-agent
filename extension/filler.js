// Form-filling logic shared by every job board. Fills ONLY from the user's saved answers;
// anything it can't answer is reported back so the user handles it.

/* exported JobFiller */
const JobFiller = (() => {
  const norm = (s) => (s || "").replace(/\s+/g, " ").replace(/[*✱]/g, "").trim().toLowerCase();

  /** Best human-readable question text for a form control. */
  function questionFor(el) {
    const bits = [];
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) bits.push(l.textContent);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) bits.push(aria);
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) labelledBy.split(/\s+/).forEach((id) => { const n = document.getElementById(id); if (n) bits.push(n.textContent); });
    const wrapLabel = el.closest("label");
    if (wrapLabel) bits.push(wrapLabel.textContent);
    if (!bits.length) {
      // Walk up to the question container (Ashby/Lever/Greenhouse all wrap each field).
      const box = el.closest("fieldset, .application-question, .field, [class*='_fieldEntry'], [class*='question'], li, .form-group, div");
      const legend = box && box.querySelector("legend, label, .application-label, .text, [class*='label']");
      if (legend) bits.push(legend.textContent);
    }
    if (el.placeholder) bits.push(el.placeholder);
    if (el.name) bits.push(el.name.replace(/[_\[\]]+/g, " "));
    return norm(bits.join(" | "));
  }

  function isRequired(el, q) {
    if (el.required || el.getAttribute("aria-required") === "true") return true;
    const box = el.closest("fieldset, .application-question, [class*='_fieldEntry'], .field, label");
    const lab = box?.querySelector("legend, label, [class*='label']")?.textContent || box?.textContent?.slice(0, 160) || "";
    return /[*✱]/.test(lab) || /\(required\)/i.test(lab);
  }

  function fillTemplate(t, company) {
    return (t || "").replace(/\[company\]/gi, company);
  }

  /** Map a question to an answer from the profile. Returns {value} | {skip:reason} | null (unknown). */
  function answerFor(q, p, job) {
    const yes = (b) => (b === true ? "Yes" : b === false ? "No" : null);
    const has = (...words) => words.some((w) => q.includes(w));
    const company = job.jobs.company;

    if (has("salary", "compensation expectation", "desired pay", "expected pay", "pay expectation"))
      return { skip: "salary question (answer it yourself)" };
    if (has("password", "verification code")) return { skip: "needs login / code" };

    if (has("first name", "given name", "legal first")) return { value: p.first_name };
    if (has("last name", "family name", "surname", "legal last")) return { value: p.last_name };
    if (has("preferred name")) return { value: p.first_name };
    if (/^(full name|name)\b/.test(q) || q === "name" || has("full name", "your name")) return { value: [p.first_name, p.last_name].filter(Boolean).join(" ") };
    if (has("email")) return { value: p.email };
    if (has("phone", "mobile")) return { value: p.phone };
    if (has("linkedin")) return { value: p.linkedin_url };
    if (has("website", "portfolio", "github", "personal site")) return p.website_url ? { value: p.website_url } : { value: "", optional: true };
    // User-saved keyword answers win over the generic rules below (after identity fields).
    // User's own keyword answers, longest keyword first.
    const extra = Object.entries(p.extra_answers || {}).sort((a, b) => b[0].length - a[0].length);
    for (const [k, v] of extra) if (k && q.includes(k)) return { value: v };

    if (has("authorized to work", "authorised to work", "legally authorized", "eligible to work", "right to work in the us", "work authorization"))
      return { value: yes(p.work_authorized_us) };
    if (has("sponsorship", "sponsor", "visa")) return { value: yes(p.needs_sponsorship) };
    if (has("how did you hear", "how did you find", "where did you hear", "source")) return { value: p.how_heard };
    if (has("notice period", "earliest start", "when can you start", "start date", "availability to start")) return { value: p.notice_period };
    if (has("current company", "current employer", "most recent employer", "company name")) return { value: p.current_company };
    if (has("current title", "job title", "current role", "most recent title")) return { value: p.current_title };
    if (has("school", "university", "college", "institution")) return { value: p.school };
    if (has("degree", "field of study", "major")) return { value: p.degree };
    if (has("graduation", "grad date", "graduated")) return { value: p.graduation };
    if (has("location", "city", "where are you based", "current address")) return { value: p.current_location };
    if (has("why do you want", "why are you interested", "why " + company.toLowerCase(), "interest in", "why this", "why us", "what excites you", "cover letter"))
      return p.why_company_template ? { value: fillTemplate(p.why_company_template, company), review: /\[product\]/i.test(p.why_company_template) } : null;
    if (has("exceptional", "accomplishment", "proud", "impressive")) return p.exceptional_text ? { value: p.exceptional_text } : null;

    // Voluntary EEO questions: decline unless the user saved an answer above.
    if (has("gender", "race", "ethnicity", "hispanic", "veteran", "disability", "sexual orientation", "transgender"))
      return { value: "Decline", eeo: true };
    return null;
  }

  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  const DECLINE = /decline|prefer not|don.?t wish|do not wish|not to (say|disclose|answer)|i don.?t want/i;
  function pickOption(options, value, eeo) {
    const v = norm(value);
    const texts = options.map((o) => norm(o.textContent || o.value));
    if (eeo) { const i = texts.findIndex((t) => DECLINE.test(t)); return i; }
    let i = texts.findIndex((t) => t === v);
    if (i < 0) i = texts.findIndex((t) => t.startsWith(v) || (v.length > 2 && t.includes(v)));
    return i;
  }

  function fillSelect(el, ans) {
    const opts = [...el.options];
    const i = pickOption(opts, ans.value, ans.eeo);
    if (i < 0) return false;
    setNativeValue(el, opts[i].value);
    return true;
  }

  function fillRadioGroup(radios, ans) {
    const labels = radios.map((r) => ({ textContent: questionFor(r).split(" | ")[0] || r.value, r }));
    const i = pickOption(labels, ans.value, ans.eeo);
    if (i < 0) return false;
    labels[i].r.click();
    return true;
  }

  /** Ashby-style Yes/No button pairs. */
  function fillButtonChoice(container, ans) {
    const btns = [...container.querySelectorAll("button")].filter((b) => /^(yes|no)$/i.test(b.textContent.trim()));
    if (!btns.length) return false;
    const b = btns.find((x) => norm(x.textContent) === norm(ans.value));
    if (!b) return false;
    b.click();
    return true;
  }

  async function attachResume(resume) {
    const inputs = [...document.querySelectorAll('input[type="file"]')];
    if (!inputs.length) return false;
    const target = inputs.find((i) => /resume|cv/.test(questionFor(i))) || inputs[0];
    const bytes = Uint8Array.from(atob(resume.b64), (c) => c.charCodeAt(0));
    const file = new File([bytes], resume.name, { type: "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    target.files = dt.files;
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  /** Fill the whole form. Returns a checklist: {filled:[], review:[], missing:[], skipped:[]} */
  async function fillForm(ctx) {
    const p = ctx.profile;
    const out = { filled: [], review: [], missing: [], skipped: [] };
    out.resume = await attachResume(ctx.resume);

    const seenRadio = new Set();
    const controls = [...document.querySelectorAll("input, textarea, select")].filter((el) => {
      if (el.disabled || el.type === "hidden" || el.type === "file" || el.type === "submit" || el.type === "button") return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 || r.height > 0 || el.type === "radio" || el.type === "checkbox";
    });

    for (const el of controls) {
      if (el.type === "radio") {
        if (seenRadio.has(el.name)) continue;
        seenRadio.add(el.name);
      }
      const box = el.closest("fieldset, .application-question, [class*='_fieldEntry'], .field") || el.parentElement;
      const q = el.type === "radio" || el.type === "checkbox"
        ? norm(box?.querySelector("legend, label, [class*='label']")?.textContent || questionFor(el))
        : questionFor(el);
      const short = q.split(" | ")[0].slice(0, 90);
      const required = isRequired(el, q);

      if (el.type === "checkbox") {
        // Consent checkboxes (privacy policy / data processing) are the only ones we tick.
        if (/privacy|consent|agree|acknowledge|terms/.test(q) && required && !el.checked) { el.click(); out.filled.push(short); }
        else if (required && !el.checked) out.missing.push(short);
        continue;
      }
      if (el.type !== "radio" && el.value && el.tagName !== "SELECT") { out.filled.push(short + " (already filled)"); continue; }

      const ans = answerFor(q, p, ctx.job);
      if (ans?.skip) { out.skipped.push(`${short}: ${ans.skip}`); if (required) out.missing.push(short); continue; }
      if (!ans || ans.value == null || ans.value === "") {
        if (required && !ans?.optional) out.missing.push(short);
        continue;
      }
      let ok = false;
      if (el.tagName === "SELECT") ok = fillSelect(el, ans);
      else if (el.type === "radio") ok = fillRadioGroup([...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)], ans);
      else if (el.getAttribute("role") === "combobox") { setNativeValue(el, ans.value); ok = false; } // typeahead: user must pick
      else { setNativeValue(el, ans.value); ok = true; }
      if (ok) (ans.review ? out.review : out.filled).push(short + (ans.review ? ": replace [Product]" : ""));
      else if (required) out.missing.push(short + " (pick the option)");
    }

    // Ashby yes/no buttons have no input element.
    document.querySelectorAll("[class*='_fieldEntry'], fieldset").forEach((c) => {
      if (!c.querySelector("button") || c.querySelector("input:not([type=hidden]), textarea, select")) return;
      const q = norm(c.querySelector("label, legend")?.textContent);
      const ans = q && answerFor(q, p, ctx.job);
      if (ans?.value && fillButtonChoice(c, ans)) out.filled.push(q.slice(0, 90));
      else if (q && /\*/.test(c.textContent.slice(0, 300))) out.missing.push(q.slice(0, 90));
    });

    return out;
  }

  const SUCCESS = /thank you for (applying|your application|your interest)|application (has been )?(submitted|received)|we.?ve received your application|successfully submitted/i;
  const isSuccessPage = () => SUCCESS.test(document.body?.innerText?.slice(0, 5000) || "") || /\/(thanks|confirmation)\b/.test(location.pathname);
  const hasCaptcha = () => !!document.querySelector("iframe[src*='recaptcha'][src*='bframe'], iframe[src*='hcaptcha'], .h-captcha, #captcha");

  function submitButton() {
    return [...document.querySelectorAll("button, input[type=submit]")].find((b) =>
      /submit( application)?|apply$|send application/i.test((b.textContent || b.value || "").trim()));
  }

  return { fillForm, isSuccessPage, hasCaptcha, submitButton, answerFor, questionFor, norm };
})();
