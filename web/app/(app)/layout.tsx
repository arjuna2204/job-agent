import Link from "next/link";
import { signOut } from "../login/actions";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav className="nav">
        <Link href="/jobs" className="brand">Job Agent</Link>
        <Link href="/jobs">Jobs</Link>
        <Link href="/settings">Settings</Link>
        <Link href="/extension">Extension</Link>
        <form action={signOut}><button className="ghost" type="submit">Sign out</button></form>
      </nav>
      <main className="wrap">{children}</main>
    </>
  );
}
