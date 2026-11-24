# Job Agent website (private beta)

Users say what jobs they want, get a daily feed of matches from the finder, approve the ones they
like, and the Chrome extension (`../extension`) fills those applications in their own browser.

```
finder.py poll (GitHub Actions, 2x/day) ──> web_sync.py ──> Supabase: jobs + per-user matches
                                                              │
Next.js site (Vercel): sign in, targets, resume, answers ─────┤
Chrome extension: Start applying -> opens approved jobs ──────┘ (/api/ext/*, per-user key)
```

## Setup
1. **Supabase**: create a project, run `supabase/migrations/0001_init.sql` in the SQL editor.
   Auth -> URL configuration: set Site URL to your Vercel URL and add `<site>/auth/callback` as a redirect.
2. **Invite people**: `insert into beta_allowlist (email) values ('friend@example.com');`
3. **Vercel**: import this repo, Root Directory = `web`, add the env vars from `.env.example`.
4. **GitHub Actions**: add repo secrets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. The finder
   workflow then runs `web_sync.py` after every poll.
5. **Extension**: `chrome://extensions` -> Developer mode -> Load unpacked -> pick `extension/`.
   Paste the site URL and the key from the site's Extension page.

## Limits to know
- Jobs come from the finder's watchlist (finance/fintech/GTM-heavy today). Add companies with
  `python finder.py add "Company"` to widen it for other users.
- The extension fills Greenhouse, Lever and Ashby forms. Workday and other portals show up in the feed
  as "you apply" (they need each user's own account).
- Auto-submit is off by default. It only submits when every required field is answered and there is
  no CAPTCHA; otherwise the job goes to "Needs you" with the reason.
