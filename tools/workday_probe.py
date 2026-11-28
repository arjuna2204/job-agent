#!/usr/bin/env python3
"""Find Workday career sites for big companies: tries tenant x server x site combinations
against Workday's public jobs endpoint. Input tools/workday_candidates.json {company: [tenants]}.
Output data/workday_found.csv: company,slug,total_jobs"""
import json, csv, sys, itertools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finder

cands = json.load(open(Path(__file__).parent / "workday_candidates.json"))
WDS = ["wd1", "wd5", "wd3", "wd12", "wd2", "wd10", "wd103", "wd108"]
def sites(t, extra):
    T = t.capitalize()
    base = ["External", "Careers", "careers", "External_Careers", "ExternalCareerSite", "External_Career_Site",
            f"{T}_Careers", f"{T}Careers", T, t, t.upper(), f"{t.upper()}_Careers", "Search", "jobs", "en-US"]
    return list(dict.fromkeys(extra + base))

def probe(slug):
    tenant, wd, site = slug.split("|")
    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    status, data = finder.http_post_json(url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, timeout=12)
    if status == 200 and data and "jobPostings" in data:
        return data.get("total", 0)
    return None

def find(item):
    company, spec = item
    tenants, extra_sites = spec.get("t", []), spec.get("s", [])
    # first: which tenant/server combos exist at all (cheap: try 'External' + extras on each server)
    for t in tenants:
        for wd in WDS:
            for s in sites(t, extra_sites):
                n = probe(f"{t}|{wd}|{s}")
                if n is not None:
                    return company, f"{t}|{wd}|{s}", n
    return company, "", 0

out = []
with ThreadPoolExecutor(max_workers=16) as ex:
    for company, slug, n in ex.map(find, cands.items()):
        out.append({"company": company, "slug": slug, "total_jobs": n})
        print(company, slug or "-", n, flush=True)
finder.DATA.mkdir(exist_ok=True)
with open(finder.DATA / "workday_found.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["company", "slug", "total_jobs"]); w.writeheader(); w.writerows(out)
print("found", sum(1 for o in out if o["slug"]), "of", len(out))
