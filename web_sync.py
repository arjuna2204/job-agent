#!/usr/bin/env python3
"""
Push the finder's job pool to the Job Agent website (Supabase) and create per-user matches.

Runs in GitHub Actions right after `python finder.py poll`:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python web_sync.py

1. Reads recent jobs (open or recently closed) from data/jobs.db.
2. Upserts them into the `jobs` table.
3. For every user with saved preferences, runs the same filter the finder uses (finder.evaluate)
   with that user's own titles / locations / max years, and inserts new rows into `matches`.
Standard library only.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import finder

WINDOW_DAYS = 30          # only sync jobs first seen in the last N days
DESC_LIMIT = 6000         # chars of description stored on the site
AUTO_ATS = {"greenhouse", "lever", "ashby"}


# ------------------------------------------------------------------ Supabase REST

def _req(method, path, body=None, prefer=None, params=""):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path + params
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "authorization": "Bearer " + key, "content-type": "application/json"}
    if prefer:
        headers["prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=finder.SSL_CTX) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:300]}") from None


def select_all(table, columns="*", params=""):
    out, start, page = [], 0, 1000
    while True:
        rows = _req("GET", table, params=f"?select={columns}{params}&offset={start}&limit={page}")
        out += rows
        if len(rows) < page:
            return out
        start += page


def upsert(table, rows, on_conflict, ignore_duplicates=False):
    pref = "resolution=" + ("ignore" if ignore_duplicates else "merge") + "-duplicates,return=minimal"
    for i in range(0, len(rows), 500):
        _req("POST", table, rows[i:i + 500], prefer=pref, params=f"?on_conflict={on_conflict}")


# ------------------------------------------------------------------ jobs

def load_recent_jobs():
    con = finder.db()
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    rows = con.execute("SELECT * FROM jobs WHERE first_seen >= ? OR (open = 1 AND posted >= ?)", (since, since)).fetchall()
    jobs = []
    for r in rows:
        desc = r["description"] or ""
        jobs.append({
            "id": r["id"], "company": r["company"], "title": r["title"], "location": r["location"],
            "remote": bool(r["remote"]), "department": r["department"], "compensation": r["compensation"] or None,
            "posted": r["posted"] or None, "first_seen": r["first_seen"], "url": r["url"],
            "apply_url": r["apply_url"] or r["url"], "ats": r["ats"], "open": bool(r["open"]),
            "min_years": finder.min_years_required(desc), "description": desc[:DESC_LIMIT],
        })
    return jobs


# ------------------------------------------------------------------ matching

def user_cfg(prefs, base):
    return {
        "title_include": prefs.get("title_keywords") or [],
        "title_exclude": prefs.get("exclude_keywords") or [],
        "locations": prefs.get("locations") or [],
        "remote_ok": bool(prefs.get("remote_ok", True)),
        "allow_any_location": not (prefs.get("locations") or []),
        "location_exclude": base.get("location_exclude", []),
        "max_age_days": prefs.get("max_age_days") or 7,
        "max_years_required": prefs.get("max_years") if prefs.get("max_years") is not None else 2,
    }


def score(job, prefs):
    """Higher = shown first: earlier-listed location, earlier-listed title keyword, auto-fillable board."""
    s = 0
    loc = (job.get("location") or "").lower()
    locs = prefs.get("locations") or []
    for i, l in enumerate(locs):
        if finder._has_any(loc, [l]):
            s += 50 - min(i, 40)
            break
    titles = prefs.get("title_keywords") or []
    t = job["title"].lower()
    for i, k in enumerate(titles):
        if finder._has_any(t, [k]):
            s += 30 - min(i, 25)
            break
    if job.get("ats") in AUTO_ATS:
        s += 10
    return s


US_REMOTE_OK = {"remote", "anywhere", "united", "states", "usa", "us", "u", "s", "americas", "america", "north",
                "hybrid", "or", "in", "the", "from", "only", "based", "first", "friendly", "nationwide", "within", "time", "zones"}


def remote_outside_us(job, prefs):
    """True for 'Remote - Dominican Republic' style postings when the user only matched on remote."""
    loc = (job.get("location") or "").lower()
    if not job.get("remote") or finder._has_any(loc, prefs.get("locations") or []):
        return False
    return any(w not in US_REMOTE_OK for w in re.findall(r"[a-z]+", loc))


def build_matches(user_id, prefs, jobs, existing_ids, applied_pairs, base_cfg):
    """Pure function: new match rows for one user."""
    if prefs.get("paused") or not (prefs.get("title_keywords") or []):
        return []
    cfg = user_cfg(prefs, base_cfg)
    alt_kw = prefs.get("resume_alt_keywords") or []
    out = []
    for j in jobs:
        if not j["open"] or j["id"] in existing_ids:
            continue
        if (finder._norm(j["company"]), finder._norm(j["title"])) in applied_pairs:
            continue
        ok, reason = finder.evaluate(dict(j, remote=1 if j["remote"] else 0), cfg)
        if not ok or remote_outside_us(j, prefs):
            continue
        out.append({
            "user_id": user_id, "job_id": j["id"], "status": "new", "score": score(j, prefs), "reason": reason,
            "resume_choice": "alt" if finder._has_any(j["title"].lower(), alt_kw) else "main",
        })
    return out


def main():
    for v in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if not os.environ.get(v):
            print(f"{v} not set; skipping website sync.")
            return 0
    base_cfg = finder.load_config()
    jobs = load_recent_jobs()
    upsert("jobs", jobs, "id")
    print(f"synced {len(jobs)} jobs")

    prefs = select_all("preferences")
    existing = select_all("matches", "user_id,job_id")
    applied = select_all("applied_elsewhere", "user_id,company,title")
    by_user = {}
    for m in existing:
        by_user.setdefault(m["user_id"], set()).add(m["job_id"])
    applied_by_user = {}
    for a in applied:
        applied_by_user.setdefault(a["user_id"], set()).add((finder._norm(a["company"]), finder._norm(a["title"])))

    total = 0
    for p in prefs:
        uid = p["user_id"]
        rows = build_matches(uid, p, jobs, by_user.get(uid, set()), applied_by_user.get(uid, set()), base_cfg)
        if rows:
            upsert("matches", rows, "user_id,job_id", ignore_duplicates=True)
        total += len(rows)
        print(f"user {uid[:8]}: {len(rows)} new matches")
    print(f"done: {total} new matches for {len(prefs)} users")
    return 0


if __name__ == "__main__":
    sys.exit(main())
