#!/usr/bin/env python
import argparse
import csv
import datetime
import multiprocessing as mp
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


def fetch_page_links(url, browser):
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

    soup = BeautifulSoup(content, "html.parser")
    return [a.get("href") for a in soup.find_all("a")]


def crawl_url(url, domain, browser, return_dict):
    """Worker: probe the URL, extract links, store result in return_dict."""
    try:
        check = requests.head(url, timeout=10, verify=False, headers=HEADERS)
        if check.status_code >= 400:
            return_dict[url] = False
            return
        items = []
        for href in fetch_page_links(url, browser):
            full = build_url(url, href)
            if full:
                items.append(full)
        return_dict[url] = items
    except requests.RequestException:
        return_dict[url] = False
    except Exception:
        return_dict[url] = False


class GetDomains:
    def __init__(
        self, domain="127.0.0.1", protocol="https", proc=3, delay=0.1, browser="chrome"
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
                    args=(url, self.domain, self.browser, return_dict),
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
                self.graph.add_node(url)
                for link in res:
                    self.graph.add_node(link)
                    self.graph.add_edge(url, link, weight=0.5, value=20)
                self.process_items(res)

            return_dict.clear()

    def process_items(self, items):
        for url in items:
            if url in self._seen:
                continue
            self._seen.add(url)
            if urlparse(url).hostname != self.domain:
                self.e.append(url)
                continue
            self.o.append(url)

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

    args = parser.parse_args()

    if args.test:
        test(args.test, args.domain, args.protocol)
    else:
        d = GetDomains(args.domain, args.protocol, args.worker, args.slowdown, args.browser)
        d.start()
        d.complete()
