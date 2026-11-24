"use server";
import { randomBytes } from "crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireUser } from "@/lib/supabase/server";

export async function rotateToken() {
  const { sb, user } = await requireUser();
  if (!user) redirect("/");
  await sb.from("profiles").update({ extension_token: randomBytes(24).toString("hex") }).eq("id", user.id);
  revalidatePath("/extension");
}
