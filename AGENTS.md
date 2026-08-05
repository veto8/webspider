# AGENTS.md

Guidance for AI agents working on this repository.

## Project

`webspider` is a Python CLI crawler that starts from a domain, follows every
internal link, and writes results to `results/<domain>/`:

- `links.csv` — successfully crawled internal pages
- `broken.csv` — links returning HTTP 4xx/5xx or failing to connect
- `external.csv` — links pointing to other domains
- `graph.html` — networkx/pyvis visualization of the link graph
- `mirror/` — (with `-m`) offline copy of pages + assets, links rewritten to
  relative paths, URL layout preserved (e.g. `/category/category_1.html` ->
  `mirror/category/category_1.html`)

`main.py` is the whole app (single file). `website/public/` is a static test
site (HTML-entity-encoded `href`s, broken links, external links) served by a
lighttpd docker container for testing.

## Commands

```sh
./run.sh                      # create venv (env/) + install deps + run
./main.py                     # crawl default domain 127.0.0.1
./main.py -d example.com -b requests     # no-browser crawl
./main.py -d 127.0.0.1 -m                # mirror site for offline use
./main.py -d example.com --serve         # serve existing mirror at :8899
./main.py -t requests -d example.com     # smoke test fetching
docker compose up -d          # start test site (in website/dockers/)
```

Run crawling against the local test site with the docker container running.

## Environment notes

- Python 3.13 available, but **no pip/venv modules are installed** in the dev
  environment. Package installs are not possible here.
- Therefore verify code statically: `python3 -m py_compile main.py`.
- Full runtime testing requires the user's machine (deps: selenium,
  beautifulsoup4, networkx, pyvis, requests; chromedriver for `-b chrome`).

## Conventions

- Keep the app in `main.py`; do not split it up without asking.
- Do not add comments unless requested.
- Do not commit unless explicitly asked.
- Preserve the CLI flags (`-d/-p/-w/-s/-b/-t`) and the `results/<domain>/`
  output layout.
- The crawler uses `mp.Process` workers writing into a `Manager` dict; keep the
  worker (`crawl_url`) as a module-level function so it is picklable.
