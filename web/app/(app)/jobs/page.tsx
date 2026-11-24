import Link from "next/link";
import { requireUser } from "@/lib/supabase/server";
import { setStatus } from "./actions";

const TABS = [
  { key: "new", label: "New matches" },
  { key: "approved", label: "Approved (queue)" },
  { key: "needs_you", label: "Needs you" },
  { key: "applied", label: "Applied" },
  { key: "skipped", label: "Skipped" },
] as const;

type Job = {
  id: string; company: string; title: string; location: string | null; remote: boolean | null;
  compensation: string | null; posted: string | null; url: string | null; apply_url: string | null;
  ats: string | null; min_years: number | null;
};
type Row = { job_id: string; status: string; reason: string | null; note: string | null;
  resume_choice: string; applied_at: string | null; jobs: Job | null };

const AUTO = new Set(["greenhouse", "lever", "ashby"]);

export default async function Jobs({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const sp = await searchParams;
  const tab = TABS.some((t) => t.key === sp.tab) ? sp.tab! : "new";
  const { sb } = await requireUser();
  const { data } = await sb
    .from("matches")
    .select("job_id,status,reason,note,resume_choice,applied_at,jobs(id,company,title,location,remote,compensation,posted,url,apply_url,ats,min_years)")
    .eq("status", tab)
    .order("score", { ascending: false })
    .order("created_at", { ascending: false })
    .limit(200);
  const rows = (data as unknown as Row[]) || [];
  const counts = await Promise.all(
    TABS.map(async (t) => {
      const { count } = await sb.from("matches").select("job_id", { count: "exact", head: true }).eq("status", t.key);
      return count ?? 0;
    })
  );

  return (
    <>
      <h1>Jobs</h1>
      <p className="muted small">New matches arrive after each daily check. Approve the ones you want, then open the Chrome extension and press <b>Start applying</b>.</p>
      <div className="tabs">
        {TABS.map((t, i) => (
          <Link key={t.key} href={`/jobs?tab=${t.key}`} className={t.key === tab ? "on" : ""}>
            {t.label} ({counts[i]})
          </Link>
        ))}
      </div>

      {tab === "new" && rows.length > 0 && (
        <form action={setStatus} className="actions">
          {rows.map((r) => <input key={r.job_id} type="hidden" name="job_id" value={r.job_id} />)}
          <input type="hidden" name="status" value="approved" />
          <button type="submit">Approve all {rows.length}</button>
        </form>
      )}

      {rows.length === 0 && <p className="card muted">Nothing here yet.</p>}
      {rows.map((r) => {
        const j = r.jobs;
        if (!j) return null;
        const auto = AUTO.has(j.ats || "");
        return (
          <div key={r.job_id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <div>
                <b>{j.company}</b>, {j.title}
                <div className="small muted">
                  {j.location || (j.remote ? "Remote" : "")}
                  {j.compensation ? ` · ${j.compensation}` : ""}
                  {j.posted ? ` · posted ${new Date(j.posted).toLocaleDateString()}` : ""}
                  {j.min_years != null ? ` · asks ${j.min_years}+ yrs` : ""}
                </div>
              </div>
              <div>
                <span className={`tag ${auto ? "ok" : "warn"}`}>{auto ? "extension fills" : `${j.ats || "other"}: you apply`}</span>{" "}
                <span className="tag">{r.resume_choice === "alt" ? "2nd resume" : "main resume"}</span>
              </div>
            </div>
            {r.note && <p className="small" style={{ color: "var(--warn)" }}>{r.note}</p>}
            <div className="actions">
              <a className="btn ghost" href={j.url || j.apply_url || "#"} target="_blank" rel="noreferrer">View posting</a>
              {tab !== "approved" && tab !== "applied" && <StatusButton id={r.job_id} status="approved" label="Approve" />}
              {tab !== "skipped" && tab !== "applied" && <StatusButton id={r.job_id} status="skipped" label="Skip" ghost />}
              {tab !== "applied" && <StatusButton id={r.job_id} status="applied" label="I applied" ghost />}
              {tab === "applied" && <StatusButton id={r.job_id} status="approved" label="Undo" ghost />}
            </div>
          </div>
        );
      })}
    </>
  );
}

function StatusButton({ id, status, label, ghost }: { id: string; status: string; label: string; ghost?: boolean }) {
  return (
    <form action={setStatus}>
      <input type="hidden" name="job_id" value={id} />
      <input type="hidden" name="status" value={status} />
      <button className={ghost ? "ghost" : ""} type="submit">{label}</button>
    </form>
  );
}
