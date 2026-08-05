import httpx

URL = "https://www.lanzarote-vulkane.de/wp-content/uploads/2019/03/Ausbruch-2.gif"
OUT = "Ausbruch-2-httpx.gif"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) webspider/1.0"}

r = httpx.get(URL, timeout=15, verify=False, headers=HEADERS, follow_redirects=True)
data = r.content
with open(OUT, "wb") as f:
    f.write(data)
print("status:", r.status_code)
print("size:", len(data))
print("headers:", dict(r.headers))
