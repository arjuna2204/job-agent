import { redirect } from "next/navigation";
import { requireUser } from "@/lib/supabase/server";
import { sendMagicLink } from "./login/actions";

export default async function Home({ searchParams }: { searchParams: Promise<{ sent?: string; error?: string }> }) {
  const { user } = await requireUser();
  if (user) redirect("/jobs");
  const sp = await searchParams;
  return (
    <main className="wrap" style={{ maxWidth: 560 }}>
      <h1>Job Agent</h1>
      <p className="muted">
        Tell it what jobs you want. Every day it checks hundreds of company job boards (Greenhouse, Lever, Ashby,
        Workday), shows you the new matches, and fills the applications you approve with your resume and saved
        answers.
      </p>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Sign in</h2>
        <p className="small muted">Private beta: invited emails only. We email you a one-time sign-in link.</p>
        {sp.sent && <p className="notice">Check your email for the sign-in link.</p>}
        {sp.error && <p className="notice" style={{ borderColor: "var(--danger)" }}>{sp.error}</p>}
        <form action={sendMagicLink}>
          <label htmlFor="email">Email</label>
          <input id="email" name="email" type="email" required autoComplete="email" />
          <div className="actions"><button type="submit">Email me a link</button></div>
        </form>
      </div>
      <h2>How it works</h2>
      <ol>
        <li>Set your targets: job titles, locations, max years of experience.</li>
        <li>Add your resume and the answers you reuse on applications.</li>
        <li>Each day, approve or skip your new matches.</li>
        <li>The Chrome extension opens each approved job and fills the form. You check it and submit.</li>
      </ol>
    </main>
  );
}
