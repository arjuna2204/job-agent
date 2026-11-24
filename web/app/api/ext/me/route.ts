import { NextResponse } from "next/server";
import { extUser } from "@/lib/ext-auth";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const r = await extUser(req);
  if ("error" in r) return r.error;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { extension_token, resume_path, resume_alt_path, ...profile } = r.profile;
  return NextResponse.json({
    profile,
    has_resume: !!resume_path,
    has_alt_resume: !!resume_alt_path,
    resume_name: resume_path?.split("/").pop() ?? null,
    resume_alt_name: resume_alt_path?.split("/").pop() ?? null,
  });
}
