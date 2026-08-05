#!/usr/bin/env python
import platform, time, json, csv, datetime, validators, requests, argparse, pickle
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.service import Service
import multiprocessing as mp
import networkx as nx
from pyvis.network import Network
from pathlib import Path


class GetDomains:
    def __init__(
        self, domain="127.0.0.1", protocol="https", proc=3, delay=0.1, browser="chrome"
    ):
        self.init_time = round(time.time())
        self.domain = domain
        self.protocol = "{0}://".format(protocol)
        self.p = proc
        self.o = []
        self.o.append("http://" + domain)
        self.graph = nx.DiGraph()
        self.c = []
        self.e = []
        self.b = []
        self.delay = delay
        self.browser = browser
        # chrome_options = Options()
        # chrome_options.add_argument("--headless=new")  # for Chrome >= 109
        # self.browser = webdriver.Chrome(options=chrome_options)

    def start(self):
        print("...start")
        mp.set_start_method("spawn")
        while len(self.o):
            time.sleep(self.delay)
            chunks = []
            for i in range(0, len(self.o), self.p):
                chunks.append(self.o[i : i + self.p])
            for i in chunks:
                jobs = []
                manager = mp.Manager()
                return_dict = manager.dict()
                for k, v in enumerate(i):
                    self.c.append(v)
                    self.o.remove(v)

                    p = mp.Process(
                        target=self.get_page_items,
                        args=(v, return_dict),
                    )
                    jobs.append(p)
                    p.start()
                # print("...tread.................")
                msg = """{0} proc: {1} \t open:{2} \t closed:{3} \t ext:{4} \t broken: {5} \t {6}  """.format(
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

                for k, v in enumerate(return_dict):
                    # Check if request url was ok
                    if return_dict[v] == False:
                        self.b.append(v)
                        self.c.remove(v)
                        continue

                    self.graph.add_node(v)
                    for ii in return_dict[v]:
                        self.graph.add_node(ii)
                        self.graph.add_edge(v, ii, weight=0.5, value=20)
                    self.process_items(return_dict[v])
            # break

    def get_page_items(self, req_url, return_dict):
        items = []
        if validators.url(req_url):
            check = requests.head(req_url)
            # print(req_url,check.status_code)
            if check.status_code in [200, 301]:
                _items = self.request_page(req_url)
                if len(_items):
                    for i in _items:
                        if i is not None:
                            if (
                                i.startswith("https://") == False
                                and i.startswith("http://") == False
                            ):
                                i = "{0}{1}{2}".format(self.protocol, self.domain, i)
                            if i[-1] == "/":
                                i = i[:-1]
                            items.append(i)
            else:
                items = False
        return_dict[req_url] = items

    def request_page(self, req_url):
        items = []
        if self.browser == "chrome":
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            browser = webdriver.Chrome(options=chrome_options)
            browser.get(req_url)
            content = browser.page_source
            browser.quit()

        elif self.browser == "firefox":
            firefox_options = webdriver.FirefoxOptions()
            firefox_options.add_argument("--headless")
            firefox_options.add_argument("--disable-gpu")
            browser = webdriver.Firefox(options=firefox_options)
            browser.get(req_url)
            content = browser.page_source
            browser.quit()

        elif self.browser == "edge":
            edge_options = EdgeOptions()
            edge_options.use_chromium = True
            edge_options.add_argument("headless")
            browser = webdriver.Edge(options=edge_options)
            browser.get(req_url)
            content = browser.page_source
            browser.quit()
        else:
            r = requests.get(req_url)
            content = r.content

        soup = BeautifulSoup(content, "html.parser")
        _items = soup.find_all("a")
        for i in _items:
            items.append(i.get("href"))

        return items

    def process_items(self, items):
        # processing here new items
        for url in items:
            # if this url is already recorded skip loop
            if url in self.c or url in self.e:
                continue

            # if the url is for external, then save it to the external list
            if (
                url.startswith("{0}{1}".format("https://", self.domain)) == False
                and url.startswith("{0}{1}".format("http://", self.domain)) == False
            ):
                if url not in self.e:
                    self.e.append(url)
                continue

            if url not in self.o and url not in self.c:
                # print("...add:\t{}".format(url))
                if url not in self.o:
                    self.o.append(url)

    def complete(self):
        print("...completed!")
        net = Network()
        # with open('GFG', 'w') as f:
        # net.from_nx(self.graph)
        # net.show("graph.html", notebook=False)
        # print(self.c);

        Path("results/{}".format(self.domain)).mkdir(parents=True, exist_ok=True)

        with open("results/{0}/links.csv".format(self.domain), "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.c:
                writer.writerow([i])

        with open("results/{0}/broken.csv".format(self.domain), "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.b:
                writer.writerow([i])

        with open("results/{0}/external.csv".format(self.domain), "w", newline="") as f:
            writer = csv.writer(f)
            for i in self.e:
                writer.writerow([i])


def test(browser, domain, protocol):
    if browser == "chrome":
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("window-size=1920,1080")
        browser = webdriver.Chrome(options=options)

        browser.get("{}://{}".format(protocol, domain))
        content = browser.page_source
        browser.quit()
        print(content)
        print("..test ok: count characters: {}".format(len(content)))

    elif browser == "firefox":
        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        browser = webdriver.Firefox(options=options)
        browser.get("https://myridia.com")
        content = browser.page_source
        browser.quit()
        print("..test ok: count characters: {}".format(len(content)))
    elif browser == "edge":
        options = EdgeOptions()
        options.use_chromium = True
        options.add_argument("headless")
        browser = webdriver.Edge(options=options)
        browser.get("https://myridia.com")
        content = browser.page_source
        browser.quit()
        print("..test ok: count characters: {}".format(len(content)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="ProgramName",
        description="What the program does",
        epilog="Text at the bottom of help",
    )
    parser.add_argument("-t", "--test")
    parser.add_argument("-d", "--domain", required=True, default="127.0.0.1")
    parser.add_argument("-p", "--protocol", default="https")
    parser.add_argument("-w", "--worker", default=5, type=int)
    parser.add_argument("-s", "--slowdown", default=0.2)
    parser.add_argument("-b", "--browser", default="chrome")
    #  self, domain="127.0.0.1", protocol="https", proc=3, delay=0.1, browser="chrome"

    # parser.add_argument("-b", "--browser")

    args = parser.parse_args()
    # print(args.test, args.browser)

    # d = GetDomains("127.0.0.1", "http", 5, 0.2, "chrome")
    # d = GetDomains("myridia.com", "https", 5, 0.2, "chrome")

    print(args.domain)
    print(args.protocol)
    print(args.worker)
    print(args.browser)
    if args.test:
        test(args.test, args.domain, args.protocol)

    elif args.domain:
        d = GetDomains(
            args.domain, args.protocol, args.worker, args.slowdown, args.browser
        )
        d.start()
        d.complete()
    else:
        print("...missing parameters")
