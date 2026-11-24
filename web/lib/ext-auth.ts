import "server-only";
import { NextResponse } from "next/server";
import { supabaseAdmin } from "./supabase/admin";

/** Resolve "Authorization: Bearer <extension_token>" to a profile row, or a 401 response. */
export async function extUser(req: Request) {
  const token = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!/^[a-f0-9]{32,128}$/.test(token)) return { error: NextResponse.json({ error: "missing or bad key" }, { status: 401 }) };
  const admin = supabaseAdmin();
  const { data: profile } = await admin.from("profiles").select("*").eq("extension_token", token).maybeSingle();
  if (!profile) return { error: NextResponse.json({ error: "unknown key" }, { status: 401 }) };
  return { admin, profile };
}
