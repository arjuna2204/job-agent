"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireUser } from "@/lib/supabase/server";

const ALLOWED = new Set(["approved", "skipped", "applied", "new"]);

export async function setStatus(f: FormData) {
  const { sb, user } = await requireUser();
  if (!user) redirect("/");
  const status = String(f.get("status"));
  const ids = f.getAll("job_id").map(String).filter(Boolean).slice(0, 200);
  if (!ALLOWED.has(status) || ids.length === 0) return;
  const patch: Record<string, unknown> = { status, updated_at: new Date().toISOString(), note: null };
  if (status === "applied") patch.applied_at = new Date().toISOString();
  await sb.from("matches").update(patch).eq("user_id", user.id).in("job_id", ids);
  revalidatePath("/jobs");
}
