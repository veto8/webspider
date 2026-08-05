#!/usr/bin/env python
import argparse
import csv
import datetime
import multiprocessing as mp
import os
import re
import time
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from pyvis.network import Network
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions

import networkx as nx

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) webspider/1.0"}

warnings.simplefilter("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ASSET_TAGS = (
    ("link", "href"),
    ("script", "src"),
    ("img", "src"),
    ("source", "src"),
    ("video", "src"),
    ("audio", "src"),
    ("embed", "src"),
    ("iframe", "src"),
    ("track", "src"),
)

URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def build_url(base, href):
    """Join a raw href against the page URL and return a normalized URL or None."""
    if not href or not isinstance(href, str):
        return None
    href = href.strip()
    if not href or href.startswith(
        ("#", "mailto:", "javascript:", "tel:", "data:", "ftp:", "file:")
    ):
        return None
    url = urljoin(base, href)
    if not url.startswith(("http://", "https://")):
        return None
    url = url.split("#", 1)[0]
    if url.endswith("/"):
        url = url[:-1]
    return url


def local_path(url):
    """Map a URL to its local path under the mirror root (preserves URL layout)."""
    p = urlparse(url)
    path = p.path or "/"
    if p.query:
        q = "".join(c if c.isalnum() else "_" for c in p.query)
        path = path.rstrip("/") + "_" + q
    if path.endswith("/"):
        path += "index.html"
    else:
        name = path.rsplit("/", 1)[-1]
        if "." not in name:
            path = path.rstrip("/") + "/index.html"
    return path.lstrip("/")


def relative_to(target_url, base_url):
    """Relative posix path from the file of base_url to the file of target_url."""
    base_dir = os.path.dirname(local_path(base_url)) or "."
    return os.path.relpath(local_path(target_url), base_dir)


def extract_url_refs(text, base):
    """Absolute asset URLs referenced via url(...) inside text (style/css content)."""
    refs = []
    for m in URL_RE.finditer(text):
        ref = m.group(2).strip()
        if not ref or ref.startswith(("#", "data:")):
            continue
        abs_ref = urljoin(base, ref)
        if urlparse(abs_ref).hostname is None:
            continue
        refs.append(abs_ref)
    return refs


def rewrite_url_refs(text, base, domain, existing=None):
    """Rewrite url(...) references in text to relative local paths."""

    def repl(m):
        q, ref = m.group(1), m.group(2)
        ref = ref.strip()
        if not ref or ref.startswith(("#", "data:")):
            return m.group(0)
        abs_ref = urljoin(base, ref)
        if urlparse(abs_ref).hostname != domain:
            return m.group(0)
        if existing is not None and local_path(abs_ref) not in existing:
            return m.group(0)
        return "url({0}{1}{0})".format(q, relative_to(abs_ref, base))

    return URL_RE.sub(repl, text)


def link_is_asset(el):
    rel = " ".join(el.get("rel") or []).lower()
    return any(k in rel for k in ("stylesheet", "icon", "preload"))


def parse_page(html_text, url):
    """Extract internal links and asset URLs from a page."""
    soup = BeautifulSoup(html_text, "html.parser")
    links, assets = [], []
    for a in soup.find_all("a", href=True):
        full = build_url(url, a["href"])
        if full:
            links.append(full)
    for tag, attr in ASSET_TAGS:
        for el in soup.find_all(tag):
            if not (el.has_attr(attr) and isinstance(el[attr], str)):
                continue
            if tag == "link" and not link_is_asset(el):
                continue
            full = build_url(url, el[attr])
            if full:
                assets.append(full)
    for el in soup.find_all(style=True):
        assets.extend(extract_url_refs(el["style"], url))
    for st in soup.find_all("style"):
        if st.string:
            assets.extend(extract_url_refs(st.string, url))
    return links, assets


def rewrite_page(html_text, page_url, domain, existing=None):
    """Rewrite a page's internal links to relative local paths for offline use.

    Only links that resolve to a saved local file (in `existing`) are rewritten;
    all others keep their original URL.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    for tag, attr in [("a", "href")] + list(ASSET_TAGS):
        for el in soup.find_all(tag):
            if not el.has_attr(attr) or not isinstance(el[attr], str):
                continue
            val = el[attr].strip()
            if not val or val.startswith(
                ("#", "mailto:", "javascript:", "tel:", "data:", "about:")
            ):
                continue
            abs_url = urljoin(page_url, val)
            if urlparse(abs_url).hostname != domain:
                continue
            if existing is not None and local_path(abs_url) not in existing:
                continue
            el[attr] = relative_to(abs_url, page_url)
    for el in soup.find_all(style=True):
        el["style"] = rewrite_url_refs(el["style"], page_url, domain, existing)
    for st in soup.find_all("style"):
        if st.string:
            st.string = rewrite_url_refs(st.string, page_url, domain, existing)
    return str(soup)


def save_file(mirror_root, url, content):
    dest = Path(mirror_root) / local_path(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8", "ignore")
    dest.write_bytes(content)


def fetch_page(url, browser):
    if browser == "chrome":
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        b = webdriver.Chrome(options=chrome_options)
        b.get(url)
        content = b.page_source
        b.quit()
    elif browser == "firefox":
        firefox_options = webdriver.FirefoxOptions()
        firefox_options.add_argument("--headless")
        firefox_options.add_argument("--disable-gpu")
        b = webdriver.Firefox(options=firefox_options)
        b.get(url)
        content = b.page_source
        b.quit()
    elif browser == "edge":
        edge_options = EdgeOptions()
        edge_options.use_chromium = True
        edge_options.add_argument("headless")
        b = webdriver.Edge(options=edge_options)
        b.get(url)
        content = b.page_source
        b.quit()
    else:
        r = requests.get(url, timeout=15, verify=False, headers=HEADERS)
        content = r.content
    return content


def crawl_url(url, domain, browser, return_dict, mirror_root=None):
    """Worker: probe the URL, extract links, optionally save page for the mirror."""
    try:
        check = requests.head(url, timeout=10, verify=False, headers=HEADERS)
        if check.status_code >= 400:
            return_dict[url] = False
            return
        html_text = fetch_page(url, browser)
        links, assets = parse_page(html_text, url)
        if browser != "requests" and not links:
            try:
                html_text = fetch_page(url, "requests")
                links, assets = parse_page(html_text, url)
            except Exception:
                pass
        if mirror_root:
            save_file(mirror_root, url, html_text)
        return_dict[url] = {"links": links, "assets": assets}
    except requests.RequestException:
        return_dict[url] = False
    except Exception as exc:
        print("...error fetching {0}: {1}".format(url, exc), flush=True)
        return_dict[url] = False


class GetDomains:
    def __init__(
        self,
        domain="127.0.0.1",
        protocol="https",
        proc=3,
        delay=0.1,
        browser="chrome",
        mirror=False,
    ):
        self.init_time = round(time.time())
        self.domain = domain
        self.protocol = protocol
        self.p = proc
        self.delay = delay
        self.browser = browser
        self.graph = nx.DiGraph()
        self.o = []
        self.c = []
        self.e = []
        self.b = []
        self._seen = set()
        self.all_assets = set()
        self.mirror_root = Path("results") / domain / "mirror" if mirror else None

        seed = self.resolve_seed()
        self.o.append(seed)
        self._seen.add(seed)

    def resolve_seed(self):
        fallback = "http" if self.protocol == "https" else "https"
        for scheme in (self.protocol, fallback):
            url = "{0}://{1}".format(scheme, self.domain)
            try:
                requests.head(url, timeout=8, verify=False, headers=HEADERS)
                return url
            except requests.RequestException:
                continue
        return "{0}://{1}".format(self.protocol, self.domain)

    def start(self):
        print("...start")
        try:
            mp.set_start_method("spawn")
        except RuntimeError:
            pass

        if self.mirror_root:
            self.mirror_root.mkdir(parents=True, exist_ok=True)

        manager = mp.Manager()
        return_dict = manager.dict()

        while self.o:
            time.sleep(self.delay)
            chunk, self.o = self.o[: self.p], self.o[self.p :]

            jobs = []
            for url in chunk:
                self.c.append(url)
                p = mp.Process(
                    target=crawl_url,
                    args=(url, self.domain, self.browser, return_dict, self.mirror_root),
                )
                jobs.append(p)
                p.start()

            msg = "...run {0} proc: {1} \t open:{2} \t closed:{3} \t ext:{4} \t broken: {5} \t {6}".format(
                datetime.timedelta(seconds=round(time.time()) - self.init_time),
                self.p,
                len(self.o),
                len(self.c),
                len(self.e),
                len(self.b),
                self.browser,
            )
            print(msg)

            for proc in jobs:
                proc.join()

            for url in chunk:
                res = return_dict.get(url)
                if res is False:
                    self.b.append(url)
                    self.c.remove(url)
                    continue
                if res is None:
                    continue
                links = res.get("links", [])
                self.all_assets.update(res.get("assets", []))
                self.graph.add_node(url)
                for link in links:
                    self.graph.add_node(link)
                    self.graph.add_edge(url, link, weight=0.5, value=20)
                self.process_items(links)

            return_dict.clear()

        if self.mirror_root:
            self.mirror_assets()
            self.rewrite_all_pages()

    def rewrite_all_pages(self):
        print("...rewriting links in saved pages")
        existing = set()
        for p in self.mirror_root.rglob("*"):
            if p.is_file():
                existing.add(p.relative_to(self.mirror_root).as_posix())
        for page in self.c:
            f = self.mirror_root / local_path(page)
            if not f.exists():
                continue
            f.write_text(rewrite_page(f.read_text(errors="ignore"), page, self.domain, existing))

    def process_items(self, items):
        for url in items:
            if url in self._seen:
                continue
            self._seen.add(url)
            if urlparse(url).hostname != self.domain:
                self.e.append(url)
                continue
            self.o.append(url)

    def mirror_assets(self):
        print("...downloading {0} assets".format(len(self.all_assets)))
        page_paths = {local_path(u) for u in self.c}
        queue = list(self.all_assets)
        seen = set()
        saved = 0
        while queue:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if urlparse(url).hostname != self.domain:
                continue
            if local_path(url) in page_paths:
                continue
            try:
                r = requests.get(url, timeout=15, verify=False, headers=HEADERS)
                if r.status_code >= 400:
                    continue
                ctype = r.headers.get("Content-Type", "")
                if "text/html" in ctype or "xhtml" in ctype:
                    continue
                if urlparse(url).path.lower().endswith(".css"):
                    text = r.text
                    for ref in extract_url_refs(text, url):
                        if urlparse(ref).hostname == self.domain:
                            queue.append(ref)
                    save_file(self.mirror_root, url, rewrite_url_refs(text, url, self.domain))
                else:
                    save_file(self.mirror_root, url, r.content)
                saved += 1
            except Exception:
                continue
        print("...assets saved: {0}".format(saved))

    def complete(self):
        print("...completed!")
        out = Path("results") / self.domain
        out.mkdir(parents=True, exist_ok=True)

        with open(out / "links.csv", "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.c:
                writer.writerow([i])

        with open(out / "broken.csv", "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.b:
                writer.writerow([i])

        with open(out / "external.csv", "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.e:
                writer.writerow([i])

        try:
            net = Network()
            net.from_nx(self.graph)
            net.write_html(str(out / "graph.html"))
            print("...graph saved to", out / "graph.html")
        except Exception as exc:
            print("...graph export failed:", exc)


def test(browser, domain, protocol):
    url = "{0}://{1}".format(protocol, domain)
    try:
        if browser == "chrome":
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("window-size=1920,1080")
            b = webdriver.Chrome(options=options)
        elif browser == "firefox":
            options = webdriver.FirefoxOptions()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            b = webdriver.Firefox(options=options)
        elif browser == "edge":
            options = EdgeOptions()
            options.use_chromium = True
            options.add_argument("headless")
            b = webdriver.Edge(options=options)
        else:
            content = requests.get(url, timeout=15, verify=False, headers=HEADERS).content
            print(content)
            print("..test ok: count characters: {0}".format(len(content)))
            return

        b.get(url)
        content = b.page_source
        b.quit()
        print(content)
        print("..test ok: count characters: {0}".format(len(content)))
    except Exception as exc:
        print("..test failed:", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="webspider",
        description="Crawl a domain and extract all linked urls and domains",
    )
    parser.add_argument("-t", "--test", choices=["chrome", "firefox", "edge", "requests"])
    parser.add_argument(
        "-d", "--domain", default="127.0.0.1", help="domain to crawl (default: 127.0.0.1)"
    )
    parser.add_argument("-p", "--protocol", default="https", choices=["http", "https"])
    parser.add_argument("-w", "--worker", default=5, type=int)
    parser.add_argument("-s", "--slowdown", default=0.2, type=float)
    parser.add_argument(
        "-b", "--browser", default="chrome", choices=["chrome", "firefox", "edge", "requests"]
    )
    parser.add_argument(
        "-m", "--mirror", action="store_true",
        help="save pages and assets under results/<domain>/mirror for offline use",
    )

    args = parser.parse_args()

    if args.test:
        test(args.test, args.domain, args.protocol)
    else:
        d = GetDomains(
            args.domain, args.protocol, args.worker, args.slowdown, args.browser, args.mirror
        )
        d.start()
        d.complete()
