#!/usr/bin/env python3
"""One-off: check a few board tokens for big companies not on Workday."""
import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finder
tests = [("KKR", "greenhouse", t) for t in ("kkr", "stage", "kkrcareers", "kkrco")] + \
        [("Global Atlantic", "greenhouse", "globalatlantic"), ("Point72", "greenhouse", "point72")]
out = []
for company, ats, slug in tests:
    ok, jobs = finder.fetch_board(ats, slug, company)
    names = {j["company"] for j in jobs[:1]}
    sample = jobs[0]["title"] if jobs else ""
    print(company, ats, slug, ok, len(jobs), sample)
    out.append({"company": company, "ats": ats, "slug": slug, "ok": ok, "jobs": len(jobs), "sample": sample})
with open(finder.DATA / "probe_misc.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
