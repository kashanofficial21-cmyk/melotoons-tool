"""YouTube search autocomplete se real high-volume keywords nikalna.

YouTube ka autocomplete = jo log ACTUAL search karte hain, sorted by popularity.
Yeh free hai, koi API key nahi chahiye. vidIQ bhi issi data pe kaam karta hai.
"""

from __future__ import annotations

import urllib.request
import urllib.parse
import json
import re
from typing import Optional


def _yt_suggest(query: str, lang: str = "en") -> list[str]:
    """YouTube search suggestions fetch karo for a query."""
    try:
        q = urllib.parse.quote(query)
        hl = "hi" if lang in ("hi", "ur", "pa") else "en"
        url = (f"https://suggestqueries.google.com/complete/search"
               f"?client=youtube&q={q}&hl={hl}&gl=IN&ds=yt")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        # Format: [query, [[suggestion, 0, []], ...], ...]
        suggestions = [item[0] for item in data[1] if isinstance(item, list) and item]
        return [str(s).strip() for s in suggestions if str(s).strip()][:10]
    except Exception:
        return []


def research_keywords(primary_keyword: str, content_summary: str,
                      language: str = "english") -> dict:
    """
    Primary keyword + content summary se real YouTube-searched keywords nikalo.
    Returns: {keywords: [...], tag_suggestions: [...]}
    """
    lang_code = "hi" if language in ("roman-urdu", "hindi") else "en"

    # Multiple queries se suggestions gather karo
    queries = [primary_keyword]

    # Content se 1-2 more queries
    words = content_summary.lower().split()
    if len(words) >= 2:
        queries.append(" ".join(words[:3]))

    # Language-specific broad query
    if lang_code == "hi":
        queries.append(primary_keyword + " hindi")
        queries.append(primary_keyword + " kahani")
    else:
        queries.append(primary_keyword + " animated")
        queries.append(primary_keyword + " shorts")

    all_suggestions = []
    seen = set()
    for q in queries[:4]:
        for s in _yt_suggest(q, lang=lang_code):
            s_clean = s.strip().lower()
            if s_clean and s_clean not in seen and len(s_clean) > 3:
                seen.add(s_clean)
                all_suggestions.append(s)

    # Clean suggestions as tags (lowercase, no #, no duplicates)
    tag_suggestions = []
    seen_t = set()
    for s in all_suggestions:
        t = re.sub(r"[#\n\r]", "", s).strip().lower()
        if t and t not in seen_t and len(t) <= 40:
            seen_t.add(t)
            tag_suggestions.append(t)

    return {
        "source_queries": queries,
        "suggestions": all_suggestions[:12],
        "tag_suggestions": tag_suggestions[:15],
    }
