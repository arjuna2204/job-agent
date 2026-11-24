import { NextResponse } from "next/server";
import { extUser } from "@/lib/ext-auth";

export const dynamic = "force-dynamic";

/** GET ?which=main|alt -> the PDF bytes, so the extension can attach it to the form. */
export async function GET(req: Request) {
  const r = await extUser(req);
  if ("error" in r) return r.error;
  const which = new URL(req.url).searchParams.get("which") === "alt" ? "alt" : "main";
  const path = (which === "alt" ? r.profile.resume_alt_path : null) || r.profile.resume_path;
  if (!path) return NextResponse.json({ error: "no resume uploaded" }, { status: 404 });
  const { data, error } = await r.admin.storage.from("resumes").download(path);
  if (error || !data) return NextResponse.json({ error: "could not read resume" }, { status: 500 });
  return new NextResponse(data, {
    headers: {
      "content-type": "application/pdf",
      "x-file-name": encodeURIComponent(path.split("/").pop() || "resume.pdf"),
      "cache-control": "no-store",
    },
  });
}
