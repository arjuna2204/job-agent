# job-agent (private)

Nightly job finder for Arjun. GitHub Actions runs `finder.py` twice a day (~11:52am and ~5:52pm ET) plus a Sunday discovery run (see
`.github/workflows/nightly.yml`), checks every watched company's Greenhouse / Lever / Ashby
board plus any Instinct links in `data/instinct_jobs.csv`, and commits:

- `data/open_matches.csv` - every open role that passes the filters in `config.json`
- `data/new_matches_*.csv` - roles that are new since the previous run
- `watchlist.csv` - companies being tracked (grows as discovery finds more)
- `data/applied.csv` - everything already applied to (never resurfaced)

Resume and application answers are NOT stored here; they stay on Arjun's Mac.
Run it now: Actions tab -> job-finder -> Run workflow.
