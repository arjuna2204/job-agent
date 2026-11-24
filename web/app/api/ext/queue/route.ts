import { NextResponse } from "next/server";
import { extUser } from "@/lib/ext-auth";

export const dynamic = "force-dynamic";

/** Approved jobs the extension can fill, oldest approval first, capped by the daily limit. */
export async function GET(req: Request) {
  const r = await extUser(req);
  if ("error" in r) return r.error;
  const { admin, profile } = r;
  const since = new Date(); since.setHours(0, 0, 0, 0);
  const { count: doneToday } = await admin.from("matches").select("job_id", { count: "exact", head: true })
    .eq("user_id", profile.id).eq("status", "applied").gte("applied_at", since.toISOString());
  const room = Math.max(0, (profile.daily_limit ?? 20) - (doneToday ?? 0));
  if (room === 0) return NextResponse.json({ jobs: [], daily_limit_reached: true });
  const { data } = await admin.from("matches")
    .select("job_id,resume_choice,jobs!inner(id,company,title,location,url,apply_url,ats,open)")
    .eq("user_id", profile.id).eq("status", "approved")
    .in("jobs.ats", ["greenhouse", "lever", "ashby"]).eq("jobs.open", true)
    .order("updated_at", { ascending: true }).limit(room);
  return NextResponse.json({ jobs: data ?? [], applied_today: doneToday ?? 0, daily_limit: profile.daily_limit });
}
