"""Tag score calculator — vidIQ-style search volume + competition proxy.

vidIQ ka actual score proprietary data pe based hai (paid API).
Hum free mein approximate karte hain:
  - YouTube autocomplete position  → search volume proxy
  - Competitor video count         → competition proxy
  - Tag length/specificity         → broad vs niche signal

Score 0-100:  High = zyada log search karte hain + competition manageable
"""

from __future__ import annotations
import re
import time
import urllib.parse
import urllib.request
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


def _yt_autocomplete_position(tag: str, hl: str = "en") -> int:
    """Kitne number pe appear hota hai autocomplete mein (1=first=highest volume).
    Returns 0 agar appear hi nahi hota."""
    try:
        words = tag.lower().split()
        if not words:
            return 0
        seed = " ".join(words[:-1]) if len(words) > 1 else words[0][:max(3, len(words[0])-2)]
        q = urllib.parse.quote(seed)
        url = (f"https://suggestqueries.google.com/complete/search"
               f"?client=firefox&q={q}&hl={hl}&gl=IN&ds=yt")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/120.0"
        })
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        suggestions = [str(s).lower() for s in (data[1] if len(data) > 1 else [])]
        for i, s in enumerate(suggestions):
            if tag.lower() in s or s in tag.lower():
                return i + 1   # 1-indexed (lower = higher volume)
        return 0
    except Exception:
        return 0


def _volume_score(position: int, n_suggestions: int = 8) -> int:
    """Position → volume score (0-60).
    Position 1 = 60 pts (most searched), position 8+ = 10 pts, not found = 5."""
    if position == 0:
        return 5
    score = max(10, 60 - (position - 1) * 7)
    return min(60, score)


def _competition_score(tag: str) -> int:
    """Tag kitna broad/niche hai → competition estimate (0-40).
    Shorter/broader = more competition = lower score.
    Niche 3-5 word phrases = less competition = higher score."""
    words = len(tag.split())
    if words >= 4:
        return 40   # very specific long-tail = low competition
    elif words == 3:
        return 32
    elif words == 2:
        return 22
    else:
        return 12   # single word = very high competition


def score_tag(tag: str, language: str = "english") -> int:
    """Single tag ka score (0-100) — TubeBuddy style: volume + competition."""
    hl = "hi" if language in ("roman-urdu", "hindi") else "en"
    pos = _yt_autocomplete_position(tag, hl=hl)
    vol = _volume_score(pos)
    comp = _competition_score(tag)
    return min(100, vol + comp)


def keyword_opportunity_score(keyword: str, language: str = "english") -> dict:
    """TubeBuddy-style keyword opportunity score.

    Score 0-100:
    - 70+: Great opportunity (high volume, low competition)
    - 40-69: Good opportunity
    - <40: Avoid (too competitive or too low volume)
    """
    hl = "hi" if language in ("roman-urdu", "hindi") else "en"
    pos = _yt_autocomplete_position(keyword, hl=hl)

    # Volume: higher autocomplete position = more searches
    vol_score = _volume_score(pos)  # 0-60

    # Competition: word count + length as proxy
    comp_score = _competition_score(keyword)  # 0-40

    total = min(100, vol_score + comp_score)

    if total >= 70:
        grade = "🟢 Great opportunity"
        advice = "Yeh keyword target karo — volume achha, competition manageable"
    elif total >= 40:
        grade = "🟡 Good opportunity"
        advice = "Theek hai — try kar sakte hain"
    else:
        grade = "🔴 Avoid"
        advice = "Ya to bahut low volume, ya bahut high competition"

    return {
        "keyword": keyword,
        "score": total,
        "volume_score": vol_score,
        "competition_score": comp_score,
        "grade": grade,
        "advice": advice,
        "autocomplete_position": pos,
    }


def score_tags_bulk(tags: list[str], language: str = "english",
                    max_workers: int = 6, log=print) -> dict[str, int]:
    """Saare tags ke scores ek saath (parallel). Returns {tag: score}."""
    if not tags:
        return {}
    log(f"[tag_score] scoring {len(tags)} tags ...")
    scores = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(score_tag, t, language): t for t in tags}
        for f in as_completed(futures):
            tag = futures[f]
            try:
                scores[tag] = f.result()
            except Exception:
                scores[tag] = 20
        time.sleep(0.05)
    log(f"[tag_score] done. avg score: {round(sum(scores.values())/len(scores)) if scores else 0}")
    return scores
