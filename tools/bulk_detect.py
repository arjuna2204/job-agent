#!/usr/bin/env python3
"""Look up the job board (Ashby/Greenhouse/Lever) for every company in tools/candidates.csv.
Writes data/detected.csv: company,source,ats,slug,jobs (blank ats = not found)."""
import csv, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finder

rows = list(csv.DictReader(open(Path(__file__).parent / "candidates.csv")))
def look(r):
    try:
        res = finder.detect_board(r["company"])
    except Exception as e:
        res = None
    return r, res
out = []
with ThreadPoolExecutor(max_workers=10) as ex:
    for i, (r, res) in enumerate(ex.map(look, rows), 1):
        ats, slug, n = res if res else ("", "", 0)
        out.append({"company": r["company"], "source": r["source"], "ats": ats, "slug": slug, "jobs": n})
        if i % 100 == 0:
            print(f"{i}/{len(rows)} checked, {sum(1 for o in out if o['ats'])} found", flush=True)
finder.DATA.mkdir(exist_ok=True)
with open(finder.DATA / "detected.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["company", "source", "ats", "slug", "jobs"])
    w.writeheader(); w.writerows(out)
print(f"Done: {sum(1 for o in out if o['ats'])} of {len(out)} have a board")
