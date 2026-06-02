"""Complete YouTube SEO Research Module — sabse comprehensive free data.

Kya kya gather karta hai:
1. YouTube Autocomplete — real searched queries (multiple layers)
2. Question Keywords — "how to", "kya hai", "kyun", "kaise" variants
3. Google Trends — keyword trending up/down + interest score
4. Competitor Video Titles — top ranking videos ke titles (yt-dlp)
5. Keyword Clusters — primary + 4-6 long-tail variants
6. Posting Strategy — niche-based best time
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import json
from typing import Optional


# ── 1) YouTube Autocomplete (multi-layer) ─────────────────────────────────

_PREFIXES = {
    "english": ["", "how to ", "best ", "why ", "what is ", "top "],
    "roman-urdu": ["", "kaise ", "kyun ", "kya hai ", "best ", "top "],
    "hindi": ["", "कैसे ", "क्यों ", "क्या है ", "best "],
}

def _yt_autocomplete(query: str, hl: str = "en") -> list[str]:
    try:
        q = urllib.parse.quote(query)
        # client=firefox returns plain JSON (not JSONP)
        url = (f"https://suggestqueries.google.com/complete/search"
               f"?client=firefox&q={q}&hl={hl}&gl=IN&ds=yt")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/120.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=6) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
        # Format: ["query", ["suggestion1", "suggestion2", ...]]
        if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
            return [str(s).strip() for s in data[1] if isinstance(s, str)][:8]
        return []
    except Exception:
        return []


# Irrelevant content tags
_IRRELEVANT = {
    "song", "songs", "status", "lyrics", "lyric", "ringtone", "mp3", "mp4",
    "download", "natok", "serial", "episode", "drama", "movie", "film",
    "natkhat", "rhymes", "rhyme", "nursery", "lullaby", "ringtones",
}

# Question/query words — yeh search queries hain, tags nahi
_QUERY_WORDS = {
    "kaise", "kyun", "kyunki", "kya", "kaun", "kab", "kahan",
    "how", "why", "what", "when", "who", "where", "which",
    "kare", "karen", "karo", "chahiye", "hoga", "hoti", "hota",
    "jata", "jate", "jati", "batao", "bataye", "bataen",
}

def _relevant(s: str) -> bool:
    words = set(s.lower().split())
    # Filter irrelevant content
    if words & _IRRELEVANT: return False
    # Filter query-format (starts with question word OR has 2+ question words)
    word_list = s.lower().split()
    if word_list and word_list[0] in _QUERY_WORDS: return False
    if len(words & _QUERY_WORDS) >= 2: return False
    # Filter too long (>5 words — too query-like)
    if len(word_list) > 5: return False
    return True


def get_keyword_clusters(primary: str, language: str = "english") -> dict:
    """Primary keyword ke around real relevant YouTube search clusters banao."""
    hl = "hi" if language in ("roman-urdu", "hindi") else "en"
    prefixes = _PREFIXES.get(language, _PREFIXES["english"])

    all_suggestions = []   # sab kuch — tags + non-relevant (awareness ke liye)
    tag_only = []           # sirf relevant — video tags ke liye
    seen = set()

    for prefix in prefixes[:3]:
        query = prefix + primary
        for s in _yt_autocomplete(query, hl=hl):
            sc = s.strip().lower()
            if sc and sc not in seen and len(sc) > 3:
                seen.add(sc)
                all_suggestions.append(s)          # sab dikhao (awareness)
                if _relevant(s):
                    tag_only.append(s)              # sirf relevant → tags
        time.sleep(0.05)

    # Intent-based (benefits/how-to) — yeh relevant hi hote hain
    intent_q = {
        "english": [f"benefits of {primary}", f"how to {primary}"],
        "roman-urdu": [f"{primary} ke fayde", f"{primary} kaise khayen"],
        "hindi": [f"{primary} के फायदे", f"{primary} कैसे खाएं"],
    }.get(language, [f"benefits of {primary}"])

    for q in intent_q[:2]:
        for s in _yt_autocomplete(q, hl=hl):
            sc = s.strip().lower()
            if sc and sc not in seen:
                seen.add(sc)
                all_suggestions.append(s)
                if _relevant(s):
                    tag_only.append(s)
        time.sleep(0.05)

    # Tags: clean + dedupe
    tags, tag_seen = [], set()
    for s in tag_only:
        t = re.sub(r"[#\n\r]", "", s).strip().lower()
        if t and t not in tag_seen and len(t) <= 50:
            tag_seen.add(t); tags.append(t)

    return {
        "all_suggestions": all_suggestions[:20],  # sab — awareness ke liye
        "tag_ready": tags[:20],                    # sirf relevant — tags ke liye
    }


# ── 2) Google Trends ───────────────────────────────────────────────────────

def get_trends(keyword: str, language: str = "english") -> dict:
    """Google Trends se keyword ka trend score aur direction."""
    geo = "PK" if language in ("roman-urdu", "hindi") else "IN"
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=300, timeout=(5, 10),
                      requests_args={"headers": {
                          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                      }})
        pt.build_payload([keyword[:100]], cat=0, timeframe="now 7-d", geo=geo, gprop="youtube")
        df = pt.interest_over_time()
        if df.empty:
            return {"score": 0, "trend": "unknown", "peak": 0}
        col = df.columns[0]
        vals = df[col].tolist()
        current = int(vals[-1]) if vals else 0
        avg = sum(vals) / len(vals) if vals else 0
        peak = max(vals) if vals else 0
        if current >= avg * 1.2:
            trend = "📈 trending up"
        elif current <= avg * 0.8:
            trend = "📉 trending down"
        else:
            trend = "➡️ stable"
        return {"score": current, "avg": round(avg, 1), "peak": int(peak), "trend": trend}
    except Exception:
        return {"score": 0, "trend": "unavailable", "peak": 0}


# ── 3) Competitor Video Analysis ───────────────────────────────────────────

def get_competitor_data(keyword: str, max_results: int = 5) -> dict:
    """Top ranking YouTube videos ke titles + views nikalo (yt-dlp)."""
    try:
        import subprocess
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--no-warnings",
             "-I", f"1:{max_results}",
             "--print", "%(view_count)s|||%(id)s|||%(title)s",
             f"ytsearch{max_results}:{keyword}"],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace"
        )
        videos = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|||", 2)
            if len(parts) == 3:
                try:
                    views = int(parts[0]) if parts[0].strip().isdigit() else 0
                    vid_id = parts[1].strip()
                    title = parts[2].strip()
                    if title:
                        videos.append({
                            "views": views,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "",
                        })
                except Exception:
                    pass
        videos.sort(key=lambda x: x["views"], reverse=True)

        # Top competitor keywords se common words nikalo
        all_words = []
        for v in videos[:5]:
            words = re.findall(r'\b\w{4,}\b', v["title"].lower())
            all_words.extend(words)
        from collections import Counter
        stop = {"this","that","with","from","your","have","been","they","were","will",
                "what","when","how","the","and","for","are","but","not","you","all",
                "can","her","was","one","our","out","did","get","has","him","his",
                "how","its","let","may","new","now","old","see","two","way","who"}
        freq = Counter(w for w in all_words if w not in stop)
        common_keywords = [w for w, _ in freq.most_common(8)]

        return {
            "top_videos": videos[:5],
            "common_keywords": common_keywords,
            "avg_views": int(sum(v["views"] for v in videos) / len(videos)) if videos else 0
        }
    except Exception:
        return {"top_videos": [], "common_keywords": [], "avg_views": 0}


# ── 4) Posting Strategy ────────────────────────────────────────────────────

_POSTING = {
    "roman-urdu": {
        "best_days": "Jumat, Shaniwaar, Itwaar",
        "best_time": "Sham 7–10 baje (PKT)",
        "reason": "Pakistani/Indian audience peak — log ghar aake phone dekhte hain",
        "first_hour": "Pehle 1 ghante mein har comment ka reply karo — algorithm boost milta hai",
        "frequency": "Roz ek video — consistency sabse bada factor hai",
    },
    "hindi": {
        "best_days": "Friday, Saturday, Sunday",
        "best_time": "Evening 7–10 PM (IST)",
        "reason": "Indian audience peak browsing time",
        "first_hour": "Reply every comment in first hour — strong engagement signal",
        "frequency": "Daily upload recommended for Shorts",
    },
    "english": {
        "best_days": "Tuesday, Wednesday, Thursday",
        "best_time": "2–4 PM or 8–10 PM (IST/PKT)",
        "reason": "Global audience + Indian/Pakistani overlap",
        "first_hour": "Reply every comment in first hour",
        "frequency": "5-7 videos/week for Shorts",
    },
}

def get_posting_strategy(language: str = "roman-urdu") -> dict:
    return _POSTING.get(language, _POSTING["roman-urdu"])


# ── 5) Master SEO Research ─────────────────────────────────────────────────

def full_research(primary_keyword: str, content_summary: str,
                  language: str = "roman-urdu", log=print) -> dict:
    """Sab kuch parallel mein: keywords + trends + competitors + strategy."""
    import concurrent.futures

    log("[seo] keywords + trends + competitors parallel chal rahe hain ...")

    def _kw():   return get_keyword_clusters(primary_keyword, language)
    def _tr():   return get_trends(primary_keyword, language)
    def _comp(): return get_competitor_data(primary_keyword, max_results=3)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_kw   = ex.submit(_kw)
        f_tr   = ex.submit(_tr)
        f_comp = ex.submit(_comp)
        kw   = f_kw.result()
        trends = f_tr.result()
        comp = f_comp.result()

    strategy = get_posting_strategy(language)
    log("[seo] done.")
    return {
        "keyword_suggestions": kw["all_suggestions"],
        "keyword_tags": kw["tag_ready"],
        "trends": trends,
        "competitors": comp,
        "posting_strategy": strategy,
    }
