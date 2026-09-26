# diagnose_fetch2.py
import httpx

urls = [
    "https://example.com",
    "https://en.wikipedia.org/wiki/Tamil_Nadu",
    "https://www.thehindu.com",
]

for url in urls:
    try:
        r = httpx.get(url, timeout=15.0, follow_redirects=True)
        print(f"{url} -> HTTP {r.status_code}")
    except Exception as e:
        print(f"{url} -> FAILED: {type(e).__name__} - {e}")