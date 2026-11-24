import { requireUser } from "@/lib/supabase/server";
import { joinList } from "@/lib/lists";
import { savePreferences, saveProfile, uploadResume } from "./actions";

type SP = Promise<{ saved?: string; error?: string; welcome?: string }>;

export default async function Settings({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const { sb } = await requireUser();
  const [{ data: p }, { data: pr }] = await Promise.all([
    sb.from("preferences").select("*").maybeSingle(),
    sb.from("profiles").select("*").maybeSingle(),
  ]);
  const extra = Object.entries((pr?.extra_answers as Record<string, string>) || {})
    .map(([k, v]) => `${k} = ${v}`).join("\n");
  const yn = (v: boolean | null | undefined) => (v === true ? "yes" : v === false ? "no" : "");
  const file = (path?: string | null) => (path ? path.split("/").pop() : "none yet");

  return (
    <>
      <h1>Settings</h1>
      {sp.welcome && <p className="notice">Welcome! Set your job targets and add your resume. Matches show up after the next daily check.</p>}
      {sp.saved && <p className="notice">Saved.</p>}
      {sp.error && <p className="notice" style={{ borderColor: "var(--danger)" }}>{sp.error}</p>}

      <form action={savePreferences} className="card">
        <h2 style={{ marginTop: 0 }}>What jobs do you want?</h2>
        <label htmlFor="title_keywords">Job title keywords (comma or new line separated)</label>
        <textarea id="title_keywords" name="title_keywords" defaultValue={joinList(p?.title_keywords)}
          placeholder="analyst, credit, capital markets, business development, sales development representative" />
        <label htmlFor="exclude_keywords">Skip titles containing</label>
        <input id="exclude_keywords" name="exclude_keywords" defaultValue={joinList(p?.exclude_keywords)} />
        <label htmlFor="locations">Locations</label>
        <input id="locations" name="locations" defaultValue={joinList(p?.locations)}
          placeholder="new york, brooklyn, jersey city, boston, chicago" />
        <label className="check"><input type="checkbox" name="remote_ok" defaultChecked={p?.remote_ok ?? true} /> Include remote (US) roles</label>
        <div className="row">
          <div>
            <label htmlFor="max_years">Max years of experience a posting can ask for</label>
            <input id="max_years" name="max_years" type="number" min={0} max={15} defaultValue={p?.max_years ?? 2} />
          </div>
          <div>
            <label htmlFor="max_age_days">Only jobs posted in the last N days</label>
            <input id="max_age_days" name="max_age_days" type="number" min={1} max={30} defaultValue={p?.max_age_days ?? 7} />
          </div>
        </div>
        <label htmlFor="resume_alt_keywords">Use my second resume for titles containing</label>
        <input id="resume_alt_keywords" name="resume_alt_keywords" defaultValue={joinList(p?.resume_alt_keywords)} />
        <label className="check"><input type="checkbox" name="paused" defaultChecked={p?.paused ?? false} /> Pause new matches</label>
        <div className="actions"><button type="submit">Save targets</button></div>
      </form>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Resumes (PDF)</h2>
        <p className="small muted">Main resume: <b>{file(pr?.resume_path)}</b>. Second resume: <b>{file(pr?.resume_alt_path)}</b>.</p>
        <form action={uploadResume}>
          <div className="row">
            <div>
              <label htmlFor="which">Which resume</label>
              <select id="which" name="which" defaultValue="main">
                <option value="main">Main resume</option>
                <option value="alt">Second resume (e.g. sales / GTM)</option>
              </select>
            </div>
            <div>
              <label htmlFor="resume">PDF file</label>
              <input id="resume" name="resume" type="file" accept="application/pdf" required />
            </div>
          </div>
          <div className="actions"><button type="submit">Upload</button></div>
        </form>
      </div>

      <form action={saveProfile} className="card">
        <h2 style={{ marginTop: 0 }}>Application answers</h2>
        <p className="small muted">The extension fills forms only from these answers. If a required question isn&apos;t covered, it stops and leaves that one for you.</p>
        <div className="row">
          <div><label htmlFor="first_name">First name</label><input id="first_name" name="first_name" defaultValue={pr?.first_name ?? ""} /></div>
          <div><label htmlFor="last_name">Last name</label><input id="last_name" name="last_name" defaultValue={pr?.last_name ?? ""} /></div>
          <div><label htmlFor="phone">Phone</label><input id="phone" name="phone" defaultValue={pr?.phone ?? ""} /></div>
          <div><label htmlFor="linkedin_url">LinkedIn URL</label><input id="linkedin_url" name="linkedin_url" defaultValue={pr?.linkedin_url ?? ""} /></div>
          <div><label htmlFor="website_url">Website / portfolio</label><input id="website_url" name="website_url" defaultValue={pr?.website_url ?? ""} /></div>
          <div><label htmlFor="current_location">Current location (City, State, Country)</label><input id="current_location" name="current_location" defaultValue={pr?.current_location ?? ""} /></div>
          <div><label htmlFor="school">School</label><input id="school" name="school" defaultValue={pr?.school ?? ""} /></div>
          <div><label htmlFor="degree">Degree</label><input id="degree" name="degree" defaultValue={pr?.degree ?? ""} /></div>
          <div><label htmlFor="graduation">Graduation (Month Year)</label><input id="graduation" name="graduation" defaultValue={pr?.graduation ?? ""} /></div>
          <div><label htmlFor="current_title">Current title</label><input id="current_title" name="current_title" defaultValue={pr?.current_title ?? ""} /></div>
          <div><label htmlFor="current_company">Current company</label><input id="current_company" name="current_company" defaultValue={pr?.current_company ?? ""} /></div>
          <div><label htmlFor="notice_period">Notice period / earliest start</label><input id="notice_period" name="notice_period" defaultValue={pr?.notice_period ?? "2 weeks"} /></div>
          <div>
            <label htmlFor="work_authorized_us">Authorized to work in the US?</label>
            <select id="work_authorized_us" name="work_authorized_us" defaultValue={yn(pr?.work_authorized_us)}>
              <option value="">Not set</option><option value="yes">Yes</option><option value="no">No</option>
            </select>
          </div>
          <div>
            <label htmlFor="needs_sponsorship">Need visa sponsorship now or later?</label>
            <select id="needs_sponsorship" name="needs_sponsorship" defaultValue={yn(pr?.needs_sponsorship)}>
              <option value="">Not set</option><option value="no">No</option><option value="yes">Yes</option>
            </select>
          </div>
          <div><label htmlFor="how_heard">How did you hear about us?</label><input id="how_heard" name="how_heard" defaultValue={pr?.how_heard ?? "Company careers page"} /></div>
          <div><label htmlFor="daily_limit">Max applications per day</label><input id="daily_limit" name="daily_limit" type="number" min={1} max={50} defaultValue={pr?.daily_limit ?? 20} /></div>
        </div>
        <label htmlFor="why_company_template">&quot;Why this company?&quot; template. Use [Company] and [Product]; you confirm [Product] on each form.</label>
        <textarea id="why_company_template" name="why_company_template" defaultValue={pr?.why_company_template ?? ""} style={{ minHeight: 140 }} />
        <label htmlFor="exceptional_text">&quot;Tell us about something exceptional you&apos;ve done&quot;</label>
        <textarea id="exceptional_text" name="exceptional_text" defaultValue={pr?.exceptional_text ?? ""} />
        <label htmlFor="extra_answers">Other answers, one per line as <code>question keyword = answer</code></label>
        <textarea id="extra_answers" name="extra_answers" defaultValue={extra}
          placeholder={"relatives = No\nin-office = Yes\npronouns = He/him"} />
        <div className="actions"><button type="submit">Save answers</button></div>
      </form>
    </>
  );
}
