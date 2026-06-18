#!/usr/bin/env python3
"""Monitor @aleabitoreddit via Camofox browser. Real-time.
Only reports tweets newer than cached max ID. First run seeds cache silently."""

import json, re, sys, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path("/opt/data/scripts/.serenity_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "last_max_id.txt"
SEEDED_FILE = CACHE_DIR / ".seeded"
CAMOFOX = "http://localhost:9377"
USER = "zhangsa"

def cf_post(path, data):
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{CAMOFOX}{path}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(data)],
        capture_output=True, text=True, timeout=20)
    return json.loads(r.stdout)

def cf_delete(path):
    try:
        subprocess.run(
            ["curl", "-s", "-X", "DELETE", f"{CAMOFOX}{path}"],
            capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, Exception):
        pass

def fetch_tweets():
    tab = cf_post("/tabs", {
        "userId": USER, "sessionKey": "serenity-monitor",
        "url": "https://x.com/aleabitoreddit"
    })
    tab_id = tab.get("tabId", "")
    if not tab_id:
        return []

    time.sleep(4)

    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{CAMOFOX}/tabs/{tab_id}/scroll",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"userId": USER, "direction": "down", "amount": 600})],
            capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": "window.scrollBy(0, 1200)"})
    time.sleep(2)

    expand_js = """(() => {
        const links = document.querySelectorAll('div[data-testid="tweet-text-show-more-link"]');
        links.forEach(el => { try { el.click(); } catch(e) {} });
        return 'clicked=' + links.length;
    })()"""
    cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": expand_js})
    time.sleep(1)
    cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": expand_js})
    time.sleep(1)

    extract_js = """JSON.stringify([...document.querySelectorAll('article')].slice(0,5).map(a => {
        const textEl = a.querySelector('[data-testid=tweetText]');
        const timeEl = a.querySelector('time');
        const links = [...a.querySelectorAll('a')];
        const statusLink = links.find(l => l.href.includes('/status/'));
        const id = statusLink ? statusLink.href.split('/status/')[1].split('?')[0].split('/')[0] : '';
        const isHers = statusLink ? statusLink.href.includes('/aleabitoreddit/status/') : false;
        if (!isHers) return null;
        const replyLink = links.find(l => l.innerText && l.innerText.startsWith('Replying to'));
        if (replyLink) return null;
        let text = textEl ? textEl.innerText : '';
        text = text.replace(/^[\\s\\u2600-\\u27BF\\u1F300-\\u1FFFF]+\\n/gm, '').trim();
        return {
            id,
            text: text,
            time: timeEl ? timeEl.getAttribute('datetime') : '',
            url: statusLink ? statusLink.href : ''
        };
    }).filter(Boolean))"""

    result = cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": extract_js})
    raw = result.get("result", "[]")
    cf_delete(f"/tabs/{tab_id}?userId={USER}")

    try:
        tweets = json.loads(raw)
    except:
        return []

    tweets = [t for t in tweets if t.get("id") and t.get("text")]
    tweets = [t for t in tweets if len(t.get("text", "")) >= 10]
    for t in tweets:
        t["id"] = t["id"].split("/")[0]
    tweets = [t for t in tweets if "/aleabitoreddit/status/" in t.get("url", "")]
    tweets.sort(key=lambda t: int(t["id"]), reverse=True)

    # Full-text fallback for truncated tweets
    for t in tweets:
        text = t.get("text", "")
        url = t.get("url", "")
        is_truncated = (
            text.endswith("\u2026")
            or (len(text) > 50 and not text.rstrip().endswith((".", "!", "?", "。", "！", "？", '"', "'")))
        )
        if is_truncated and url:
            full = _fetch_full_text(url)
            if full and len(full) > len(text):
                t["text"] = full

    return tweets

def _fetch_full_text(tweet_url):
    try:
        tab = cf_post("/tabs", {
            "userId": USER, "sessionKey": "fulltext-fallback",
            "url": tweet_url
        })
        tab_id = tab.get("tabId", "")
        if not tab_id:
            return None
        time.sleep(4)
        try:
            subprocess.run(
                ["curl", "-s", "-X", "POST", f"{CAMOFOX}/tabs/{tab_id}/scroll",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"userId": USER, "direction": "down", "amount": 400})],
                capture_output=True, text=True, timeout=8)
        except:
            pass
        time.sleep(1.5)
        for _ in range(3):
            cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": """(() => {
                let n = 0;
                document.querySelectorAll('[data-testid="tweet-text-show-more-link"]').forEach(el => { try { el.click(); n++; } catch(e) {} });
                return n;
            })()"""})
            time.sleep(0.8)
        result = cf_post(f"/tabs/{tab_id}/evaluate", {"userId": USER, "expression": """(() => {
            const el = document.querySelector('[data-testid="tweetText"]');
            if (el) return el.innerText;
            const article = document.querySelector('article');
            if (!article) return '';
            const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
            let text = '';
            let node;
            while (node = walker.nextNode()) text += node.textContent;
            return text;
        })()"""})
        cf_delete(f"/tabs/{tab_id}?userId={USER}")
        return result.get("result", "")
    except:
        return None

def main():
    tweets = fetch_tweets()
    if not tweets:
        sys.exit(0)

    max_id = max(int(t["id"]) for t in tweets)

    if not SEEDED_FILE.exists():
        CACHE_FILE.write_text(str(max_id))
        SEEDED_FILE.touch()
        cf_delete(f"/sessions/{USER}")
        sys.exit(0)

    last_max = 0
    if CACHE_FILE.exists():
        try: last_max = int(CACHE_FILE.read_text().strip())
        except: pass

    new_tweets = [t for t in tweets if int(t["id"]) > last_max]

    if not new_tweets:
        CACHE_FILE.write_text(str(max(max_id, last_max)))
        cf_delete(f"/sessions/{USER}")
        sys.exit(0)

    CACHE_FILE.write_text(str(max_id))
    cf_delete(f"/sessions/{USER}")

    print(json.dumps({
        "count": len(new_tweets),
        "tweets": new_tweets,
        "checked_at": datetime.now(timezone.utc).isoformat()
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
