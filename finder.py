#!/usr/bin/env python3
"""
Job finder: polls public job-board APIs (Greenhouse, Lever, Ashby) for a
watchlist of companies, discovers new companies, filters postings against
your criteria, and tracks everything in a local SQLite database.

Standard library only - no pip installs needed.

Commands (run from this folder):
  python3 finder.py detect                 find which job board each watchlist company uses
  python3 finder.py poll                   check every watchlist company for new matching jobs
  python3 finder.py add "Ramp" "Mercury"   add companies by name (board auto-detected)
  python3 finder.py add --url https://jobs.ashbyhq.com/somecompany
  python3 finder.py discover --search      find new companies via search API (needs brave_api_key)
  python3 finder.py discover --commoncrawl find new companies from the Common Crawl web archive
  python3 finder.py import-urls links.txt  pull company board slugs out of any text file of URLs
  python3 finder.py export                 rewrite data/open_matches.csv from the database
  python3 finder.py rescore                re-apply config.json filters to all stored jobs
  python3 finder.py applied "Co" "Title"   log a job you applied to yourself (never shown/applied again)
  python3 finder.py applied --list         show everything you've applied to
  python3 finder.py check-links data/instinct_jobs.csv   check Instinct's links: open?, posted, years asked
"""
import argparse
import csv
import html
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
WATCHLIST_PATH = ROOT / "watchlist.csv"
DB_PATH = DATA / "jobs.db"
WATCH_FIELDS = ["company", "ats", "slug", "source", "status", "added"]
UA = "Mozilla/5.0 (Macintosh) personal-job-finder/1.0"
ATS_LIST = ["greenhouse", "lever", "ashby"]  # tried by `detect`; workday is added from links


# ---------------------------------------------------------------- utilities

def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ssl_context():
    try:
        import certifi  # python.org Mac installs often lack system certs
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def http_get_json(url, headers=None, timeout=20, retries=2):
    """Return (status_code, parsed_json_or_None). status 0 = network error."""
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                body = r.read().decode("utf-8", errors="replace")
                try:
                    return r.status, json.loads(body)
                except json.JSONDecodeError:
                    return r.status, None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, None
        except Exception as e:  # timeouts, DNS, SSL
            if attempt < retries:
                time.sleep(1.5)
                continue
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                print("SSL error: run 'Install Certificates.command' in your Python folder "
                      "(Applications/Python 3.x) or 'pip3 install certifi'.", file=sys.stderr)
            return 0, None
    return 0, None


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(s):
    if not s:
        return ""
    s = html.unescape(s)  # Greenhouse double-escapes
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = WS_RE.sub(" ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def ms_to_iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return ""


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ------------------------------------------------------------- ATS fetchers

def board_url(ats, slug):
    q = urllib.parse.quote(slug, safe="")
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{q}/jobs?content=true"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{q}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{q}?includeCompensation=true"
    raise ValueError(ats)


def parse_greenhouse(data, company, slug):
    out = []
    for j in (data or {}).get("jobs", []) or []:
        loc = (j.get("location") or {}).get("name", "") or ""
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) or [] if o.get("name"))
        depts = ", ".join(d.get("name", "") for d in j.get("departments", []) or [] if d.get("name"))
        out.append({
            "id": f"greenhouse:{slug}:{j.get('id')}",
            "company": company, "ats": "greenhouse", "slug": slug,
            "title": (j.get("title") or "").strip(),
            "location": loc or offices,
            "remote": int("remote" in (loc + " " + offices).lower()),
            "department": depts,
            "url": j.get("absolute_url", ""),
            "apply_url": j.get("absolute_url", ""),
            "posted": j.get("first_published") or j.get("updated_at") or "",
            "description": html_to_text(j.get("content", ""))[:20000],
            "compensation": "",
        })
    return out


def parse_lever(data, company, slug):
    out = []
    if not isinstance(data, list):
        return out
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or ([cats.get("location")] if cats.get("location") else [])
        loc = " | ".join(l for l in locs if l)
        wt = (j.get("workplaceType") or "").lower()
        desc = j.get("descriptionPlain") or html_to_text(j.get("description", ""))
        for lst in j.get("lists", []) or []:
            desc += "\n\n" + (lst.get("text") or "") + "\n" + html_to_text(lst.get("content", ""))
        desc += "\n\n" + (j.get("additionalPlain") or "")
        sal = j.get("salaryRange") or {}
        comp = ""
        if sal.get("min") or sal.get("max"):
            comp = f"{sal.get('currency', '')} {sal.get('min', '')}-{sal.get('max', '')} {sal.get('interval', '')}".strip()
        out.append({
            "id": f"lever:{slug}:{j.get('id')}",
            "company": company, "ats": "lever", "slug": slug,
            "title": (j.get("text") or "").strip(),
            "location": loc,
            "remote": int(wt == "remote" or "remote" in loc.lower()),
            "department": ", ".join(x for x in [cats.get("department"), cats.get("team")] if x),
            "url": j.get("hostedUrl", ""),
            "apply_url": j.get("applyUrl") or j.get("hostedUrl", ""),
            "posted": ms_to_iso(j.get("createdAt")) if j.get("createdAt") else "",
            "description": desc.strip()[:20000],
            "compensation": comp,
        })
    return out


def parse_ashby(data, company, slug):
    out = []
    for j in (data or {}).get("jobs", []) or []:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        for s in j.get("secondaryLocations", []) or []:
            if isinstance(s, dict) and s.get("location"):
                locs.append(s["location"])
        loc = " | ".join(l for l in locs if l)
        wt = (j.get("workplaceType") or "").lower()
        comp = ((j.get("compensation") or {}).get("compensationTierSummary")) or ""
        out.append({
            "id": f"ashby:{slug}:{j.get('id')}",
            "company": company, "ats": "ashby", "slug": slug,
            "title": (j.get("title") or "").strip(),
            "location": loc,
            # Ashby's isRemote flag is set on many hybrid/office roles, so rely on workplaceType + location text
            "remote": int(wt == "remote" or "remote" in loc.lower()),
            "department": ", ".join(x for x in [j.get("department"), j.get("team")] if x),
            "url": j.get("jobUrl", ""),
            "apply_url": j.get("applyUrl") or j.get("jobUrl", ""),
            "posted": j.get("publishedAt") or "",
            "description": (j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")))[:20000],
            "compensation": comp,
        })
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}

# Workday: slug format "tenant|wdN|site", e.g. "td|wd3|TD_Bank_Careers"
WD_SEARCH_TERMS = ["analyst", "associate", "sales", "credit", "investment", "operations"]


def http_post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json",
                                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            return r.status, json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def wd_posted_iso(text):
    t = (text or "").lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        d = 0
    elif "yesterday" in t:
        d = 1
    else:
        m = re.search(r"(\d+)\+?\s*days?", t)
        d = int(m.group(1)) if m else 60
    return (now - timedelta(days=d)).replace(microsecond=0).isoformat()


def fetch_workday(slug, company, cfg=None):
    """List a Workday career site's jobs via its public JSON endpoint; fetch descriptions only
    for jobs whose title and location already pass the filters (keeps big banks fast)."""
    cfg = cfg or load_config()
    try:
        tenant, wd, site = slug.split("|")
    except ValueError:
        return False, []
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    seen, out, ok_any = set(), [], False
    for term in WD_SEARCH_TERMS:
        for offset in range(0, 200, 20):
            status, data = http_post_json(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset,
                                                            "searchText": term})
            if status != 200 or not data:
                break
            ok_any = True
            posts = data.get("jobPostings") or []
            for jp in posts:
                path = jp.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                job = {"id": f"workday:{slug}:{path.rsplit('_', 1)[-1]}", "company": company, "ats": "workday",
                       "slug": slug, "title": (jp.get("title") or "").strip(), "location": jp.get("locationsText") or "",
                       "remote": int("remote" in (jp.get("locationsText") or "").lower()), "department": "",
                       "url": f"https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}",
                       "apply_url": f"https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}/apply",
                       "posted": wd_posted_iso(jp.get("postedOn")), "description": "", "compensation": ""}
                # cheap pre-check before paying for the detail call
                pre, _ = evaluate(job, dict(cfg, max_years_required=None))
                if pre:
                    st, det = http_get_json(base + path)
                    info = (det or {}).get("jobPostingInfo") or {}
                    job["description"] = html_to_text(info.get("jobDescription", ""))[:20000]
                    if info.get("startDate"):
                        job["posted"] = info["startDate"] + "T00:00:00+00:00"
                out.append(job)
            if len(posts) < 20:
                break
    return ok_any, out



def board_exists(ats, data):
    if ats == "lever":
        return isinstance(data, list)
    return isinstance(data, dict) and isinstance(data.get("jobs"), list)


def fetch_workable(slug, company):
    status, data = http_get_json(f"https://apply.workable.com/api/v1/widget/accounts/{urllib.parse.quote(slug)}?details=true")
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return False, []
    out = []
    for j in data["jobs"]:
        loc = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)
        out.append({"id": f"workable:{slug}:{j.get('shortcode')}", "company": data.get("name") or company,
                    "ats": "workable", "slug": slug, "title": (j.get("title") or "").strip(), "location": loc,
                    "remote": int(bool(j.get("telecommuting")) or "remote" in loc.lower()), "department": j.get("department") or "",
                    "url": j.get("url") or j.get("shortlink") or "", "apply_url": j.get("application_url") or j.get("url") or "",
                    "posted": (j.get("published_on") or j.get("created_at") or "") + ("T00:00:00+00:00" if len(j.get("published_on") or "") == 10 else ""),
                    "description": html_to_text(j.get("description", ""))[:20000], "compensation": ""})
    return True, out


def fetch_bamboohr(slug, company):
    base = f"https://{slug}.bamboohr.com/careers"
    status, data = http_get_json(base + "/list")
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("result"), list):
        return False, []
    out = []
    for j in data["result"]:
        loc = j.get("location") or {}
        locs = ", ".join(x for x in [loc.get("city"), loc.get("state")] if x) if isinstance(loc, dict) else str(loc)
        job = {"id": f"bamboohr:{slug}:{j.get('id')}", "company": company, "ats": "bamboohr", "slug": slug,
               "title": (j.get("jobOpeningName") or "").strip(), "location": locs,
               "remote": int(bool(j.get("isRemote")) or "remote" in locs.lower()), "department": j.get("departmentLabel") or "",
               "url": f"{base}/{j.get('id')}", "apply_url": f"{base}/{j.get('id')}", "posted": "", "description": "",
               "compensation": ""}
        st, det = http_get_json(f"{base}/{j.get('id')}/detail")
        op = ((det or {}).get("result") or {}).get("jobOpening") or {}
        job["description"] = html_to_text(op.get("description", ""))[:20000]
        if op.get("datePosted"):
            job["posted"] = op["datePosted"][:10] + "T00:00:00+00:00"
        out.append(job)
    return True, out


def fetch_board(ats, slug, company):
    """Return (ok, jobs). ok=False means the board could not be read."""
    if ats == "workday":
        return fetch_workday(slug, company)
    if ats == "workable":
        return fetch_workable(slug, company)
    if ats == "bamboohr":
        return fetch_bamboohr(slug, company)
    status, data = http_get_json(board_url(ats, slug))
    if ats == "greenhouse" and (status != 200 or not board_exists(ats, data)):
        # boards hosted in Greenhouse's EU region live on a separate API host
        status, data = http_get_json(board_url(ats, slug).replace("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"))
    if status != 200 or not board_exists(ats, data):
        return False, []
    return True, PARSERS[ats](data, company, slug)


# ---------------------------------------------------------------- URL parsing

SLUG_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%~-]+)", re.I)),
]
WORKABLE_RE = re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)", re.I)
BAMBOO_RE = re.compile(r"https?://([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)", re.I)
WORKDAY_RE = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)
BAD_SLUGS = {"embed", "v1", "jobs", "job_board", "api", "search", "robots.txt", "favicon.ico", "sitemap.xml", ""}


def slugs_from_text(text):
    found = set()
    for m in WORKABLE_RE.finditer(text):
        if m.group(1).lower() not in ("j", "api", "jobs"):
            found.add(("workable", m.group(1)))
    for m in BAMBOO_RE.finditer(text):
        found.add(("bamboohr", m.group(1).lower()))
    for m in WORKDAY_RE.finditer(text):
        tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if site.lower() not in ("wday", "job"):
            found.add(("workday", f"{tenant}|{wd}|{site}"))
    for ats, pat in SLUG_PATTERNS:
        for m in pat.finditer(text):
            slug = urllib.parse.unquote(m.group(1)).strip().strip(".")
            if slug.lower() not in BAD_SLUGS:
                found.add((ats, slug))
    return found


def candidate_slugs(name):
    base = name.lower().strip()
    base = re.sub(r"[,.]?\s+(inc|llc|ltd|co|corp|corporation|technologies|labs|hq)\.?$", "", base)
    words = re.findall(r"[a-z0-9]+", base)
    cands = ["".join(words), "-".join(words)]
    if words:
        cands.append(words[0])
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def detect_board(name, prefer=("ashby", "greenhouse", "lever")):
    """Try likely slugs on every ATS and keep the board with the most jobs
    (a company can leave a stale board behind on another ATS). Returns (ats, slug, n_jobs) or None."""
    found = []
    for slug in candidate_slugs(name):
        for ats in ATS_LIST:
            ok, jobs = fetch_board(ats, slug, name)
            if ok:
                found.append((len(jobs), -prefer.index(ats) if ats in prefer else -9, ats, slug))
    if not found:
        return None
    n, _, ats, slug = max(found)
    return ats, slug, n


# ------------------------------------------------------------------ watchlist

def load_watchlist():
    if not WATCHLIST_PATH.exists():
        return []
    with open(WATCHLIST_PATH, newline="") as f:
        return [{k: (r.get(k) or "").strip() for k in WATCH_FIELDS} for r in csv.DictReader(f)]


def save_watchlist(rows):
    with open(WATCHLIST_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WATCH_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in WATCH_FIELDS})


def known_boards(rows):
    return {(r["ats"], r["slug"].lower()) for r in rows if r["ats"] and r["slug"]}


# ------------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, company TEXT, ats TEXT, slug TEXT, title TEXT,
  location TEXT, remote INTEGER, department TEXT, url TEXT, apply_url TEXT,
  posted TEXT, description TEXT, compensation TEXT,
  first_seen TEXT, last_seen TEXT, open INTEGER DEFAULT 1,
  match INTEGER DEFAULT 0, match_reason TEXT,
  status TEXT DEFAULT 'new', notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match, open, status);
"""
# status lifecycle: new -> shortlisted / skip -> prepared -> applied


def db():
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    con.executescript(SCHEMA)
    return con


def store_jobs(con, ats, slug, jobs, cfg):
    """Upsert jobs for one board; mark vanished ones closed. Returns list of NEW matching jobs."""
    ts = now_iso()
    new_matches = []
    seen_ids = []
    for j in jobs:
        seen_ids.append(j["id"])
        match, reason = evaluate(j, cfg)
        row = con.execute("SELECT id FROM jobs WHERE id=?", (j["id"],)).fetchone()
        if row:
            con.execute("""UPDATE jobs SET title=?, location=?, remote=?, department=?, url=?, apply_url=?,
                           description=?, compensation=?, last_seen=?, open=1, match=?, match_reason=?
                           WHERE id=?""",
                        (j["title"], j["location"], j["remote"], j["department"], j["url"], j["apply_url"],
                         j["description"], j["compensation"], ts, match, reason, j["id"]))
        else:
            con.execute("""INSERT INTO jobs (id, company, ats, slug, title, location, remote, department, url,
                           apply_url, posted, description, compensation, first_seen, last_seen, open, match,
                           match_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                        (j["id"], j["company"], ats, slug, j["title"], j["location"], j["remote"],
                         j["department"], j["url"], j["apply_url"], j["posted"], j["description"],
                         j["compensation"], ts, ts, match, reason))
            if match:
                new_matches.append(j)
    q = "UPDATE jobs SET open=0 WHERE ats=? AND slug=? AND open=1"
    if seen_ids:
        q += " AND id NOT IN (%s)" % ",".join("?" * len(seen_ids))
    con.execute(q, [ats, slug] + seen_ids)
    return new_matches


# -------------------------------------------------------------------- filters

def _has_any(text, terms):
    for t in terms:
        t = t.lower().strip()
        if not t:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text):
            return t
    return None


WORDNUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15}
_NUM = r"(\d{1,2}|" + "|".join(WORDNUM) + r")"
YEARS_RE = re.compile(
    _NUM + r"\s*(?:\(\d{1,2}\)\s*)?(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*" + _NUM + r"\s*)?\+?\s*"
    r"(?:full[- ]time\s+)?years?(?:'|’)?s?\b(?P<tail>[^.\n;]{0,80})", re.I)
REQ_HINT = re.compile(r"experience|background|working|work in|work at|in (?:a |an )?\w+|selling|closing|"
                      r"building|managing|track record|as an?|post-grad|professional|relevant|industry|of ", re.I)
NOT_REQ = re.compile(r"\b(ago|old|history|anniversary|founded|since|of growth|vesting|warranty|in a row|running)\b", re.I)


def min_years_required(text):
    """Smallest minimum years of experience the posting asks for, or None if it never says."""
    best = None
    for m in YEARS_RE.finditer(text or ""):
        tail = m.group("tail") or ""
        if NOT_REQ.search(tail[:30]):
            continue
        a = m.group(1).lower()
        n = WORDNUM.get(a, None) if not a.isdigit() else int(a)
        if n is None or n > 20:
            continue
        best = n if best is None else min(best, n)
    return best


def evaluate(job, cfg):
    title = job["title"].lower()
    inc = _has_any(title, cfg.get("title_include", []))
    if not inc:
        return 0, "title not in target list"
    exc = _has_any(title, cfg.get("title_exclude", []))
    if exc:
        return 0, f"title excluded ({exc})"
    loc = (job.get("location") or "").lower()
    loc_hit = None
    foreign = _has_any(loc, cfg.get("location_exclude", []))
    if foreign and not _has_any(loc, cfg.get("locations", []) + ["united states", "usa", "us-remote", "remote us", "remote - us"]):
        return 0, f"location outside target ({foreign})"
    if not cfg.get("allow_any_location"):
        loc_hit = _has_any(loc, cfg.get("locations", []))
        remote_ok = cfg.get("remote_ok") and job.get("remote") and "remote" in loc
        if not loc_hit and not remote_ok:
            return 0, f"location ({job.get('location') or 'unknown'})"
    max_age = cfg.get("max_age_days")
    if max_age and job.get("posted"):
        try:
            posted = datetime.fromisoformat(job["posted"].replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            if posted < datetime.now(timezone.utc) - timedelta(days=int(max_age)):
                return 0, f"older than {max_age} days"
        except ValueError:
            pass
    cap = cfg.get("max_years_required")
    yrs = min_years_required(job.get("description", "")) if cap is not None else None
    if yrs is not None and yrs > int(cap):
        return 0, f"asks for {yrs}+ years"
    yrs_note = f", asks {yrs} yrs" if yrs is not None else ", years not stated"
    return 1, f"title '{inc}'" + yrs_note + (f", location '{loc_hit}'" if loc_hit else (", remote" if job.get("remote") else ""))


# ------------------------------------------------------------------- commands

APPLIED_PATH = DATA / "applied.csv"
APPLIED_FIELDS = ["company", "title", "job_id", "url", "date", "source"]


def _norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def load_applied():
    if not APPLIED_PATH.exists():
        return []
    with open(APPLIED_PATH, newline="") as f:
        return list(csv.DictReader(f))


def record_applied(company, title, job_id="", url="", source="manual"):
    DATA.mkdir(exist_ok=True)
    new = not APPLIED_PATH.exists()
    with open(APPLIED_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=APPLIED_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"company": company, "title": title, "job_id": job_id, "url": url,
                    "date": datetime.now().strftime("%Y-%m-%d"), "source": source})


def already_applied(company, title, job_id="", applied=None):
    """Matches by exact job id, or same company + same normalized title (catches reposts of the same role)."""
    applied = load_applied() if applied is None else applied
    c, t = _norm(company), _norm(title)
    for a in applied:
        if job_id and a.get("job_id") == job_id:
            return True
        if _norm(a.get("company")) == c and _norm(a.get("title")) == t:
            return True
    return False


def sync_applied(con):
    """Mark every stored job that matches applied.csv as status 'applied' so it never resurfaces."""
    applied = load_applied()
    if not applied:
        return 0
    n = 0
    for r in con.execute("SELECT id, company, slug, title FROM jobs WHERE status != 'applied'").fetchall():
        if already_applied(r["company"], r["title"], r["id"], applied) or already_applied(r["slug"], r["title"], r["id"], applied):
            con.execute("UPDATE jobs SET status='applied' WHERE id=?", (r["id"],))
            n += 1
    con.commit()
    return n


EXPORT_FIELDS = ["status", "company", "title", "location", "remote", "department", "compensation",
                 "posted", "first_seen", "url", "apply_url", "match_reason", "ats", "slug", "id", "notes"]


def export_csv(con, path, where, params=()):
    sync_applied(con)
    if "status!='skip'" in where:
        where = where.replace("status!='skip'", "status NOT IN ('skip','applied')")
    rows = con.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY first_seen DESC, company", params).fetchall()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in EXPORT_FIELDS})
    return len(rows)


def poll_boards(con, cfg, boards, label="watchlist"):
    """boards: list of (company, ats, slug). Returns (new_matches, failed_boards)."""
    results = {}

    def work(b):
        company, ats, slug = b
        return b, fetch_board(ats, slug, company)

    with ThreadPoolExecutor(max_workers=int(cfg.get("workers", 8))) as ex:
        for b, res in ex.map(work, boards):
            results[b] = res
    new_matches, failed = [], []
    for (company, ats, slug), (ok, jobs) in results.items():
        if not ok:
            failed.append((company, ats, slug))
            continue
        new_matches += store_jobs(con, ats, slug, jobs, cfg)
    con.commit()
    return new_matches, failed, results


def close_inactive(con, boards):
    """Hide jobs from any board that isn't on the active watchlist (paused companies,
    or boards discovery checked and rejected), so results only show companies you track."""
    con.execute("CREATE TEMP TABLE IF NOT EXISTS active_boards (k TEXT PRIMARY KEY)")
    con.execute("DELETE FROM active_boards")
    con.executemany("INSERT OR IGNORE INTO active_boards VALUES (?)",
                    [(f"{a}:{sl.lower()}",) for _, a, sl in boards])
    con.execute("UPDATE jobs SET open=0 WHERE open=1 AND (ats || ':' || lower(slug)) NOT IN (SELECT k FROM active_boards)")
    con.commit()


def cmd_poll(args):
    cfg = load_config()
    rows = load_watchlist()
    boards = [(r["company"], r["ats"], r["slug"]) for r in rows
              if r["ats"] and r["slug"] and r["status"] not in ("paused", "not_found")]
    if not boards:
        print("No boards to poll. Run: python3 finder.py detect")
        return
    print(f"Polling {len(boards)} company boards...")
    con = db()
    close_inactive(con, boards)
    new_matches, failed, _ = poll_boards(con, cfg, boards)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    if new_matches:
        ids = [j["id"] for j in new_matches]
        path = DATA / f"new_matches_{stamp}.csv"
        export_csv(con, path, "id IN (%s)" % ",".join("?" * len(ids)), ids)
        print(f"\n{len(new_matches)} NEW matching jobs -> {path.relative_to(ROOT)}")
        for j in sorted(new_matches, key=lambda x: x["company"].lower()):
            print(f"  - {j['company']}: {j['title']} ({j['location'] or 'n/a'})")
    else:
        print("\nNo new matching jobs this run.")
    n = export_csv(con, DATA / "open_matches.csv", "match=1 AND open=1 AND status!='skip'")
    print(f"{n} open matches total -> data/open_matches.csv")
    if failed:
        print(f"{len(failed)} boards failed to load (network issue or board moved): "
              + ", ".join(f"{c}" for c, _, _ in failed[:15]) + (" ..." if len(failed) > 15 else ""))


def cmd_detect(args):
    rows = load_watchlist()
    todo = [r for r in rows if (not r["ats"] or not r["slug"]) and (args.retry or r["status"] != "not_found")]
    if not todo:
        print("Every company already has a board (or was not found; use --retry).")
        return
    print(f"Detecting boards for {len(todo)} companies...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        found = list(ex.map(lambda r: (r, detect_board(r["company"])), todo))
    for r, res in found:
        if res:
            r["ats"], r["slug"], n = res
            r["status"] = "ok"
            print(f"  ✓ {r['company']}: {r['ats']}/{r['slug']} ({n} jobs)")
        else:
            r["status"] = "not_found"
            print(f"  ✗ {r['company']}: no Greenhouse/Lever/Ashby board found (may use Workday or another site)")
    save_watchlist(rows)


def cmd_add(args):
    rows = load_watchlist()
    known = known_boards(rows)
    names = {r["company"].lower() for r in rows}
    for url in args.url or []:
        for ats, slug in slugs_from_text(url):
            if (ats, slug.lower()) in known:
                print(f"  already watching {ats}/{slug}")
                continue
            rows.append({"company": args.name or slug, "ats": ats, "slug": slug, "source": "manual",
                         "status": "ok", "added": now_iso()[:10]})
            known.add((ats, slug.lower()))
            print(f"  + {ats}/{slug}")
    for name in args.companies:
        if name.lower() in names:
            print(f"  already on watchlist: {name}")
            continue
        res = detect_board(name)
        row = {"company": name, "source": "manual", "added": now_iso()[:10],
               "ats": res[0] if res else "", "slug": res[1] if res else "",
               "status": "ok" if res else "not_found"}
        rows.append(row)
        names.add(name.lower())
        print(f"  + {name}: " + (f"{res[0]}/{res[1]} ({res[2]} jobs)" if res else "no board found"))
    save_watchlist(rows)


def screen_and_add(slugs, source, cfg, limit):
    """Poll unknown boards once; add those with >=1 matching job to the watchlist."""
    rows = load_watchlist()
    known = known_boards(rows)
    cache_path = DATA / "screened.txt"
    DATA.mkdir(exist_ok=True)
    screened = set(cache_path.read_text().split()) if cache_path.exists() else set()
    uniq = {}
    for a, sl in slugs:
        key = (a, sl.lower())
        if key not in known and f"{a}:{sl.lower()}" not in screened:
            uniq.setdefault(key, (a, sl))
    fresh = sorted(uniq.values())
    if limit:
        fresh = fresh[:limit]
    if not fresh:
        print("No new boards to screen.")
        return
    print(f"Screening {len(fresh)} new company boards for matching jobs...")
    con = db()
    boards = [(s, a, s) for a, s in fresh]
    _, _, results = poll_boards(con, cfg, boards, label=source)
    with open(cache_path, "a") as f:  # remember what we've checked so the next run moves on to new boards
        for (_, a, sl), (ok, _) in results.items():
            if ok:
                f.write(f"{a}:{sl.lower()}\n")
    added = 0
    for (company, ats, slug), (ok, jobs) in results.items():
        if ok and any(evaluate(j, cfg)[0] for j in jobs) and in_industry(jobs, cfg):
            rows.append({"company": slug, "ats": ats, "slug": slug, "source": source,
                         "status": "ok", "added": now_iso()[:10]})
            added += 1
            print(f"  + {ats}/{slug}")
    save_watchlist(rows)
    close_inactive(con, [(r["company"], r["ats"], r["slug"]) for r in rows
                         if r["ats"] and r["slug"] and r["status"] not in ("paused", "not_found")])
    n = export_csv(con, DATA / "open_matches.csv", "match=1 AND open=1 AND status!='skip'")
    print(f"Added {added} companies with matching roles. {n} open matches total -> data/open_matches.csv")


def in_industry(jobs, cfg):
    """True if the company's postings read like finance/fintech (keeps discovery on-target).
    Looks at the 'about us' part of each posting, whole words only, and needs several distinct terms."""
    terms = [t.lower() for t in cfg.get("industry_keywords", [])]
    if not terms:
        return True
    text = " ".join((j.get("description") or "")[:1500] for j in jobs[:10]).lower()
    hits = {t: len(re.findall(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", text)) for t in terms}
    distinct = sum(1 for v in hits.values() if v)
    return distinct >= int(cfg.get("industry_min_hits", 3)) and sum(hits.values()) >= int(cfg.get("industry_min_mentions", 5))


def brave_search(query, key, freshness="pm"):
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": 20, "freshness": freshness})
    status, data = http_get_json(url, headers={"X-Subscription-Token": key})
    if status != 200 or not data:
        print(f"  search failed ({status}) for: {query}")
        return []
    return [r.get("url", "") for r in (data.get("web") or {}).get("results", [])]


def _cdx_get(api, params, tries=5):
    """One Common Crawl index request with backoff; their server often returns 503/504 under load."""
    url = f"{api}?{urllib.parse.urlencode(params)}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            wait = 10 * (i + 1)
            print(f"    HTTP {e.code}, retrying in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            wait = 10 * (i + 1)
            print(f"    {type(e).__name__}, retrying in {wait}s...")
            time.sleep(wait)
    return None


def commoncrawl_slugs(max_pages, ats_filter=None, n_indexes=3):
    status, colls = http_get_json("https://index.commoncrawl.org/collinfo.json", timeout=40)
    if status != 200 or not colls:
        print("Could not reach Common Crawl index.")
        return set()
    patterns = {"greenhouse": ["boards.greenhouse.io/*", "job-boards.greenhouse.io/*"],
                "lever": ["jobs.lever.co/*"], "ashby": ["jobs.ashbyhq.com/*"]}
    patterns = [p for a, ps in patterns.items() if not ats_filter or a in ats_filter for p in ps]
    found = set()
    for coll in colls[:n_indexes]:  # newest crawls first; older ones add boards the newest missed
        api = coll["cdx-api"]
        print(f"Common Crawl index {coll['id']}")
        for pat in patterns:
            for page in range(max_pages):
                # pageSize=1 keeps each request small so the server doesn't time out
                body = _cdx_get(api, {"url": pat, "output": "json", "fl": "url", "page": page, "pageSize": 1})
                if body is None:
                    print(f"  {pat} page {page}: gave up after retries")
                    break
                if not body.strip():
                    break
                before = len(found)
                found |= slugs_from_text(body)
                print(f"  {pat} page {page}: +{len(found) - before} boards (total {len(found)})")
                time.sleep(2)
    return found


def cmd_discover(args):
    cfg = load_config()
    slugs = set()
    if args.search:
        key = cfg.get("brave_api_key", "").strip()
        if not key:
            print("Add a Brave Search API key to config.json (brave_api_key) to use --search.")
        else:
            for q in cfg.get("discovery_queries", []):
                urls = brave_search(q, key)
                got = slugs_from_text("\n".join(urls))
                print(f"  {len(got):>3} boards  <- {q}")
                slugs |= got
                time.sleep(1.1)
    if args.commoncrawl:
        slugs |= commoncrawl_slugs(args.max_pages, args.ats.split(",") if args.ats else None, args.indexes)
    if not (args.search or args.commoncrawl):
        print("Choose --search and/or --commoncrawl")
        return
    screen_and_add(slugs, "search" if args.search else "commoncrawl", cfg, args.limit)


def cmd_import_urls(args):
    text = Path(args.file).read_text(errors="replace")
    slugs = slugs_from_text(text)
    print(f"Found {len(slugs)} job-board links in {args.file}")
    screen_and_add(slugs, "import", load_config(), args.limit)


def cmd_check_links(args):
    """Check a CSV of job links (e.g. Instinct's finds): is each posting still open, when was it
    posted, how many years does it ask for, pay. Adds the companies to the watchlist (source=instinct)."""
    cfg = load_config()
    rows = list(csv.DictReader(open(args.file, newline="")))
    boards = {}
    for r in rows:
        url = r.get("url", "")
        m = re.search(r"[?&]gh_jid=(\d+)", url)
        found = slugs_from_text(url)
        r["_job_id"] = ""
        if found:
            ats, slug = sorted(found)[0]
            r["_ats"], r["_slug"] = ats, slug
            tail = url.rstrip("/").split("/")[-1].split("?")[0]
            r["_job_id"] = tail.rsplit("_", 1)[-1] if ats == "workday" else tail
            boards[(ats, slug)] = None
        elif m:
            r["_ats"], r["_job_id"] = "greenhouse_embed", m.group(1)
    print(f"Fetching {len(boards)} job boards...")
    with ThreadPoolExecutor(max_workers=int(cfg.get("workers", 8))) as ex:
        res = dict(zip(boards, ex.map(lambda b: fetch_board(b[0], b[1], b[1]), boards)))
    con = db()
    wl = load_watchlist()
    known = known_boards(wl)
    added = 0
    out_fields = list(rows[0].keys())
    out_fields = [f for f in out_fields if not f.startswith("_")] + ["live", "posted", "min_years", "comp", "check_note"]
    for r in rows:
        r.update(live="", posted="", min_years="", comp="", check_note="")
        if r.get("_ats") in ATS_LIST + ["workday", "workable", "bamboohr"]:
            ok, jobs = res.get((r["_ats"], r["_slug"]), (False, []))
            if not ok:
                r["check_note"] = "board not readable"
            else:
                j = next((x for x in jobs if x["id"].endswith(":" + r["_job_id"]) or r["_job_id"] in x["url"]), None)
                if not j:
                    r["live"] = "no"
                else:
                    y = min_years_required(j["description"])
                    r.update(live="yes", posted=(j["posted"] or "")[:10], min_years="" if y is None else y,
                              comp=j["compensation"])
                    store_jobs(con, r["_ats"], r["_slug"], [j], cfg)
                if (r["_ats"], r["_slug"].lower()) not in known:
                    wl.append({"company": r.get("company") or r["_slug"], "ats": r["_ats"], "slug": r["_slug"],
                               "source": "instinct", "status": "ok", "added": now_iso()[:10]})
                    known.add((r["_ats"], r["_slug"].lower()))
                    added += 1
        else:
            r["check_note"] = "not an Ashby/Greenhouse/Lever link; check manually"
    con.commit()
    save_watchlist(wl)
    out = Path(args.file).with_name(Path(args.file).stem + "_checked.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    live = sum(1 for r in rows if r["live"] == "yes")
    closed = sum(1 for r in rows if r["live"] == "no")
    print(f"{live} still open, {closed} closed, {len(rows) - live - closed} need a manual check.")
    print(f"Added {added} companies to the watchlist. Details -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


def cmd_export(args):
    con = db()
    n = export_csv(con, DATA / "open_matches.csv", "match=1 AND open=1 AND status!='skip'")
    print(f"{n} open matches -> data/open_matches.csv")


def cmd_rescore(args):
    """Re-apply config.json filters to every stored job (after you edit criteria)."""
    cfg = load_config()
    con = db()
    n = 0
    for r in con.execute("SELECT * FROM jobs").fetchall():
        j = dict(r)
        if j["ats"] == "ashby" and j["remote"] and "remote" not in (j["location"] or "").lower():
            j["remote"] = 0
        m, reason = evaluate(j, cfg)
        con.execute("UPDATE jobs SET remote=?, match=?, match_reason=? WHERE id=?", (j["remote"], m, reason, j["id"]))
        n += m
    con.commit()
    k = export_csv(con, DATA / "open_matches.csv", "match=1 AND open=1 AND status!='skip'")
    print(f"{n} matching jobs in history; {k} open -> data/open_matches.csv")


def cmd_status(args):
    """Update a job's status, e.g. after applying: finder.py status <id> applied"""
    con = db()
    cur = con.execute("UPDATE jobs SET status=?, notes=COALESCE(?, notes) WHERE id=?",
                      (args.status, args.note, args.id))
    con.commit()
    if args.status == "applied" and cur.rowcount:
        r = con.execute("SELECT company, title, url FROM jobs WHERE id=?", (args.id,)).fetchone()
        if not already_applied(r["company"], r["title"], args.id):
            record_applied(r["company"], r["title"], args.id, r["url"], "finder")
    print("updated" if cur.rowcount else "no job with that id")


def cmd_applied(args):
    """Log a job you applied to yourself: finder.py applied "Ramp" "Partner Development Representative" """
    if args.list:
        for a in load_applied():
            print(f"{a['date']}  {a['company']}: {a['title']}")
        return
    if already_applied(args.company, args.title):
        print("Already logged.")
        return
    record_applied(args.company, args.title, source="manual")
    n = sync_applied(db())
    print(f"Logged. {n} matching job(s) in the database marked applied.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll").set_defaults(fn=cmd_poll)
    d = sub.add_parser("detect")
    d.add_argument("--retry", action="store_true", help="retry companies previously not found")
    d.set_defaults(fn=cmd_detect)
    a = sub.add_parser("add")
    a.add_argument("companies", nargs="*")
    a.add_argument("--url", action="append")
    a.add_argument("--name", help="company name to use with --url")
    a.set_defaults(fn=cmd_add)
    dc = sub.add_parser("discover")
    dc.add_argument("--search", action="store_true")
    dc.add_argument("--commoncrawl", action="store_true")
    dc.add_argument("--max-pages", type=int, default=10)
    dc.add_argument("--indexes", type=int, default=3, help="how many recent crawls to search")
    dc.add_argument("--ats", default="ashby,greenhouse", help="comma list: ashby,greenhouse,lever")
    dc.add_argument("--limit", type=int, default=1500, help="max new boards to screen per run")
    dc.set_defaults(fn=cmd_discover)
    iu = sub.add_parser("import-urls")
    iu.add_argument("file")
    iu.add_argument("--limit", type=int, default=0)
    iu.set_defaults(fn=cmd_import_urls)
    sub.add_parser("export").set_defaults(fn=cmd_export)
    sub.add_parser("rescore").set_defaults(fn=cmd_rescore)
    cl = sub.add_parser("check-links", help="check a CSV of job links (company,title,url columns)")
    cl.add_argument("file")
    cl.set_defaults(fn=cmd_check_links)
    ap = sub.add_parser("applied", help="log a job you applied to outside the agent")
    ap.add_argument("company", nargs="?")
    ap.add_argument("title", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.set_defaults(fn=cmd_applied)
    st = sub.add_parser("status")
    st.add_argument("id")
    st.add_argument("status", choices=["new", "shortlisted", "skip", "prepared", "applied", "rejected", "interview"])
    st.add_argument("--note")
    st.set_defaults(fn=cmd_status)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
