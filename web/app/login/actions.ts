"use server";
import { redirect } from "next/navigation";
import { supabaseServer } from "@/lib/supabase/server";
import { supabaseAdmin } from "@/lib/supabase/admin";

export async function sendMagicLink(form: FormData) {
  const email = String(form.get("email") || "").trim().toLowerCase();
  if (!email.includes("@")) redirect("/?error=" + encodeURIComponent("Enter a valid email."));
  const { data: invited } = await supabaseAdmin()
    .from("beta_allowlist").select("email").ilike("email", email).maybeSingle();
  if (!invited) redirect("/?error=" + encodeURIComponent("That email isn't on the beta list yet."));
  const sb = await supabaseServer();
  const { error } = await sb.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback` },
  });
  if (error) redirect("/?error=" + encodeURIComponent(error.message));
  redirect("/?sent=1");
}

export async function signOut() {
  const sb = await supabaseServer();
  await sb.auth.signOut();
  redirect("/");
}
