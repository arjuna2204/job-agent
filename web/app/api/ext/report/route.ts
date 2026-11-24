import { NextResponse } from "next/server";
import { extUser } from "@/lib/ext-auth";

export const dynamic = "force-dynamic";
const OK = new Set(["applying", "applied", "needs_you", "failed", "approved", "skipped"]);

/** Body: { job_id, status, note? } */
export async function POST(req: Request) {
  const r = await extUser(req);
  if ("error" in r) return r.error;
  const body = await req.json().catch(() => ({}));
  const status = String(body.status || "");
  const jobId = String(body.job_id || "");
  if (!OK.has(status) || !jobId) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const patch: Record<string, unknown> = {
    status, note: body.note ? String(body.note).slice(0, 500) : null, updated_at: new Date().toISOString(),
  };
  if (status === "applied") patch.applied_at = new Date().toISOString();
  const { error } = await r.admin.from("matches").update(patch).eq("user_id", r.profile.id).eq("job_id", jobId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
