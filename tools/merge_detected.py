#!/usr/bin/env python3
"""Merge data/detected.csv into watchlist.csv: fill boards for existing names, add new companies,
skip any board (ats+slug) already on the list."""
import csv, re, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finder
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
rows = finder.load_watchlist()
by_name = {norm(r["company"]): r for r in rows}
boards = {(r["ats"], r["slug"].lower()) for r in rows if r["ats"] and r["slug"]}
today = datetime.date.today().isoformat()
added = filled = dup = 0
for d in csv.DictReader(open(finder.DATA / "detected.csv")):
    if not d["ats"]:
        continue
    key = (d["ats"], d["slug"].lower())
    if key in boards:
        dup += 1
        continue
    r = by_name.get(norm(d["company"]))
    if r and not r["ats"]:
        r.update(ats=d["ats"], slug=d["slug"], status="ok"); filled += 1
    elif not r:
        r = {"company": d["company"], "ats": d["ats"], "slug": d["slug"], "source": d["source"], "status": "ok", "added": today}
        rows.append(r); by_name[norm(d["company"])] = r; added += 1
    else:
        continue
    boards.add(key)
finder.save_watchlist(rows)
live = sum(1 for r in rows if r["ats"] and r["slug"] and r["status"] not in ("not_found",))
print(f"filled {filled}, added {added}, skipped {dup} duplicate boards. Companies with a job board: {live} (list total {len(rows)})")
