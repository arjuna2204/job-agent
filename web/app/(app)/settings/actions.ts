"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireUser } from "@/lib/supabase/server";
import { parseList } from "@/lib/lists";

const str = (f: FormData, k: string) => {
  const v = String(f.get(k) ?? "").trim();
  return v || null;
};
const yesNo = (f: FormData, k: string) => {
  const v = f.get(k);
  return v === "yes" ? true : v === "no" ? false : null;
};

export async function savePreferences(f: FormData) {
  const { sb, user } = await requireUser();
  if (!user) redirect("/");
  const maxYears = Math.max(0, Math.min(15, Number(f.get("max_years") ?? 2)));
  const maxAge = Math.max(1, Math.min(30, Number(f.get("max_age_days") ?? 7)));
  const { error } = await sb.from("preferences").upsert({
    user_id: user.id,
    title_keywords: parseList(f.get("title_keywords")),
    exclude_keywords: parseList(f.get("exclude_keywords")),
    locations: parseList(f.get("locations")),
    remote_ok: f.get("remote_ok") === "on",
    max_years: maxYears,
    max_age_days: maxAge,
    resume_alt_keywords: parseList(f.get("resume_alt_keywords")),
    paused: f.get("paused") === "on",
    updated_at: new Date().toISOString(),
  });
  if (error) redirect("/settings?error=" + encodeURIComponent(error.message));
  revalidatePath("/settings");
  redirect("/settings?saved=prefs");
}

export async function saveProfile(f: FormData) {
  const { sb, user } = await requireUser();
  if (!user) redirect("/");
  const extra: Record<string, string> = {};
  String(f.get("extra_answers") || "")
    .split("\n")
    .forEach((line) => {
      const i = line.indexOf("=");
      if (i > 0) extra[line.slice(0, i).trim().toLowerCase()] = line.slice(i + 1).trim();
    });
  const { error } = await sb.from("profiles").update({
    first_name: str(f, "first_name"),
    last_name: str(f, "last_name"),
    phone: str(f, "phone"),
    linkedin_url: str(f, "linkedin_url"),
    website_url: str(f, "website_url"),
    current_location: str(f, "current_location"),
    school: str(f, "school"),
    degree: str(f, "degree"),
    graduation: str(f, "graduation"),
    current_title: str(f, "current_title"),
    current_company: str(f, "current_company"),
    work_authorized_us: yesNo(f, "work_authorized_us"),
    needs_sponsorship: yesNo(f, "needs_sponsorship"),
    notice_period: str(f, "notice_period"),
    how_heard: str(f, "how_heard"),
    why_company_template: str(f, "why_company_template"),
    exceptional_text: str(f, "exceptional_text"),
    extra_answers: extra,
    daily_limit: Math.max(1, Math.min(50, Number(f.get("daily_limit") ?? 20))),
    updated_at: new Date().toISOString(),
  }).eq("id", user.id);
  if (error) redirect("/settings?error=" + encodeURIComponent(error.message));
  revalidatePath("/settings");
  redirect("/settings?saved=profile");
}

export async function uploadResume(f: FormData) {
  const { sb, user } = await requireUser();
  if (!user) redirect("/");
  const which = f.get("which") === "alt" ? "alt" : "main";
  const file = f.get("resume");
  if (!(file instanceof File) || file.size === 0) redirect("/settings?error=Choose+a+PDF+first");
  if (file.type !== "application/pdf" || file.size > 4_000_000)
    redirect("/settings?error=" + encodeURIComponent("Resume must be a PDF under 4 MB."));
  // Keep the original file name: recruiters see it.
  const safeName = file.name.replace(/[^\w.\- ]+/g, "_").slice(0, 120);
  const path = `${user.id}/${which}/${safeName}`;
  const { error } = await sb.storage.from("resumes").upload(path, file, { upsert: true, contentType: "application/pdf" });
  if (error) redirect("/settings?error=" + encodeURIComponent(error.message));
  await sb.from("profiles").update(which === "alt" ? { resume_alt_path: path } : { resume_path: path }).eq("id", user.id);
  revalidatePath("/settings");
  redirect("/settings?saved=resume");
}
