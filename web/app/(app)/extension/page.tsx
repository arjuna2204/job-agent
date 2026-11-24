import { requireUser } from "@/lib/supabase/server";
import { rotateToken } from "./actions";

export default async function ExtensionPage() {
  const { sb } = await requireUser();
  const { data: pr } = await sb.from("profiles").select("extension_token").maybeSingle();
  const site = process.env.NEXT_PUBLIC_SITE_URL;
  return (
    <>
      <h1>Chrome extension</h1>
      <div className="card">
        <ol>
          <li>Download the extension folder and in Chrome open <code>chrome://extensions</code>, turn on Developer mode, and click <b>Load unpacked</b>. (Chrome Web Store listing coming later.)</li>
          <li>Open the extension and paste the site URL and your key below.</li>
          <li>Press <b>Start applying</b>. It opens your approved jobs one at a time (Greenhouse, Lever and Ashby forms), fills them from your saved answers, attaches the right resume, and shows a checklist. You review and click Submit.</li>
          <li>Anything it can&apos;t answer (a new question, a CAPTCHA, a login) moves to <b>Needs you</b> with the reason.</li>
        </ol>
      </div>
      <div className="card">
        <label>Site URL</label>
        <code>{site}</code>
        <label>Your extension key (keep it private, it lets the extension read your answers and resume)</label>
        <code>{pr?.extension_token}</code>
        <form action={rotateToken} className="actions">
          <button className="danger" type="submit">Make a new key (the old one stops working)</button>
        </form>
      </div>
    </>
  );
}
