import { NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabase/server";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  if (code) {
    const sb = await supabaseServer();
    const { error } = await sb.auth.exchangeCodeForSession(code);
    if (error) return NextResponse.redirect(new URL("/?error=" + encodeURIComponent(error.message), url.origin));
    // First visit: send them to settings to fill in their targets and resume.
    const { data: prefs } = await sb.from("preferences").select("title_keywords").maybeSingle();
    const next = prefs && prefs.title_keywords?.length ? "/jobs" : "/settings?welcome=1";
    return NextResponse.redirect(new URL(next, url.origin));
  }
  return NextResponse.redirect(new URL("/", url.origin));
}
