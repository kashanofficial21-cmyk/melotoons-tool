"""Video -> viral YouTube Shorts metadata (title / description / tags).

Pipeline:
  1. Whisper (local, free) — audio transcript + language detect
  2. LLM (Groq → Cerebras → Gemini, auto-fallback) — metadata generate

Formula (proven from @wwmMeloToons channel data):
  - Title: matched language, curiosity hook, 1 emoji
  - Description: SEO-structured, engagement question, 3-5 hashtags
  - Tags: vidIQ-style 10-15 focused tags
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional


class AnalyzerError(Exception):
    pass


def is_configured() -> bool:
    """Koi bhi LLM key set hai to True."""
    return bool(
        os.environ.get("GROQ_API_KEY") or
        os.environ.get("CEREBRAS_API_KEY") or
        os.environ.get("GEMINI_API_KEY") or
        os.environ.get("GOOGLE_API_KEY")
    )


# --------------------------------------------------------------------------- #
# Base tags — MeloToons channel ke liye hamesha high daily search wale tags
# Yeh EVERY video mein auto-add honge (content-specific tags ke saath)
# --------------------------------------------------------------------------- #
_BASE_TAGS = [
    "new animated kahani",
    "animated story hindi urdu",
    "3d animated kahani",
    "baccho ki kahaniya",
    "animated moral story hindi",
    "animated shorts hindi",
    "cartoon story hindi",
    "baccho ki kahani cartoon",
    "hindi urdu animated story",
    "melotoons",
    "melotoons shorts",
]

# --------------------------------------------------------------------------- #
# Prompt — yahi tool ka dimaag hai
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 GOLDEN RULE — IS KE BAGHAIR KUCH NAHI HOGA 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IS VIDEO KA ASLI SUBJECT JO TRANSCRIPT/VISUALS MEIN HAI — WOHI USE KARO.
SYSTEM PROMPT KE KISI BHAI EXAMPLE KO REAL CONTENT MAT SAMJHO.

❌ FORBIDDEN: Agar transcript mein "billi" nahi → titles mein "Billi Ki Kahani" BILKUL NAHI
❌ FORBIDDEN: Agar transcript mein "sabzi/fruit" nahi → "Doctor ne chhupaya" wale titles NAHI
❌ FORBIDDEN: Template se copy-paste titles — har video ALAG hoti hai

✅ PROCESS:
  1. PEHLE transcript + visuals parho → ASLI subject identify karo
  2. PHIR us subject ke liye titles/tags banao
  3. Agar transcript mein koi character/topic hai → WAHI use karo, koi aur nahi

LANGUAGE RULE:
  LANGUAGE_MODE = roman-urdu  → SIRF Latin/English letters (a-z). NO Devanagari. NO Arabic script.
  LANGUAGE_MODE = english     → Natural English only.
  LANGUAGE_MODE = hindi       → Devanagari Hindi script.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tum vidIQ Boost level ka YouTube SEO expert ho — MeloToons channel ke liye.
Har output mein vidIQ "Triple Keyword Rule" + "Optimize Score 100/100" achieve karo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHANNEL INFO (context only — content force mat karo)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Channel: MeloToons — AI 3D Pixar-style desi animated shorts
Audience: Pakistani + Indian (Roman Urdu/Hindi speakers)
Possible content types (jo VIDEO MEIN HAI woh dekho):
  • Cute animals (jo bhi video mein hai — dog, cat, bird, etc.)
  • Cute children characters
  • Talking food/objects
  • Desi situations (school, ghar, dukaan, etc.)
  ❌ Avoid: rags-to-riches motivational, dark/violent

BRAND TAGS (always include): "melotoons", "melotoons shorts"
WRONG TAGS (never use): "cartoon" alone, "animation" alone, "viral", "trending", "funny video"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 0 — TRANSCRIPT SE ACTUAL WORDS COPY KARO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGE_MODE = {mode}

MANDATORY FIRST ACTION:
  Transcript mein se 3-5 KEY NOUNS identify karo (character, topic, action, setting).
  LANGUAGE CONVERSION RULE:
    - Agar LANGUAGE_MODE = roman-urdu → Devanagari/Arabic words ko NATURAL Roman Urdu mein likho
    - English loanwords bilkul OK hain: "fruits", "health", "doctor", "school", etc.
    - ❌ FORBIDDEN: Devanagari copy-paste into Roman Urdu keyword (jaise "फूरूट्स" → write "Fruits" not "Phuruts")
    - ✅ CORRECT: "फूरूट्स खाओ" → Roman Urdu keyword: "Fruits Khao Sehat Banao"
    - ✅ CORRECT: "बिल्ली ने सीखा" → Roman Urdu keyword: "Billi Ne Seekha" (natural transliteration)

  Example: transcript "Ahmed ne school mein sabak seekha" → keyword: "Ahmed School Sabak Story"
  Example: transcript "ek kutte ne apni zindagi bacha li" → keyword: "Kutta Zindagi Bacha Story"
  Example: transcript "10 minute mein weight lose karo" → keyword: "10 Minute Weight Loss Tips"
  Example: transcript "Once a child was walking..." → keyword: "Child Walking Story Moral" (english mode)

  ❌ DO NOT INVENT: Agar transcript mein "kahani" nahi → primary keyword mein "kahani" mat lagao
  ❌ DO NOT INVENT: Agar transcript mein "billi" nahi → "billi" mat lagao
  ❌ DO NOT INVENT: Agar transcript mein "moral" nahi → "moral story" mat lagao
  ✅ USE TRANSCRIPT CONTENT: Primary keyword = natural translation of actual transcript words

PRIMARY KEYWORD = transcript ke actual content se natural 3-5 word phrase (in LANGUAGE_MODE).
  NO template defaults. NO "ek kahani", NO "dil ko chhoone wali" unless transcript mein hai.

TEEN JAGAH SAME KEYWORDS:
  [TITLE] → primary keyword pehle 40 chars mein
  [DESCRIPTION] → line 1 mein EXACT primary keyword
  [TAGS] → tag[0] = primary keyword

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — 5 TITLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rules: primary keyword first 40 chars + 1 emoji + NO # + 40-60 chars total.

5 EMOTIONAL HOOKS — write in LANGUAGE_MODE language (english=English, roman-urdu=Roman Urdu):
  HOOK 1 — CURIOSITY:   "[primary_keyword] — [curiosity phrase in LANGUAGE_MODE] 😱"
  HOOK 2 — EMOTION:     "[transcript_character/subject] [emotional action from video] 🥺"
  HOOK 3 — QUESTION:    "[Question about transcript_topic in LANGUAGE_MODE]? 🤔"
  HOOK 4 — SHOCK:       "[transcript_fact/event] — [shock phrase in LANGUAGE_MODE] 😮"
  HOOK 5 — LESSON:      "[transcript_theme/moral] — [lesson phrase in LANGUAGE_MODE] 💡"

LANGUAGE EXAMPLES:
  english mode:    "Elephants Tied With Rope — This Will Shock You 😱"
  roman-urdu mode: "Haathi Rassi Se Bandha — Yeh Sun Kar Hairaan Ho Jaoge 😱"

⚠️ CRITICAL: Replace [transcript_*] with ONLY words/phrases found in the actual transcript above.
   ALL titles must be in LANGUAGE_MODE — NO mixing English titles with Roman Urdu hooks or vice versa.

SCORE: keyword first 40 chars (+30), length 40-60 (+20), emotion hook (+20), 1 emoji (+15), no # (+10)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — DESCRIPTION (150+ words)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINE 1: primary keyword EXACT + hook. Ending reveal nahi.
LINE 2-3: keyword variations (synonyms, related phrases from actual content).
ENGAGEMENT Q: Comment trigger (👇).
CTA: Like + Subscribe.
CHAPTERS: 0:00 Shuruat / 0:05 [actual topic] / 0:45 Moral
HASHTAGS (exactly 3, end mein): #[ActualTopic] #Shorts #[NicheFormat]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — TAGS (400-480 chars, NO #, 20-30 tags)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
L1 EXACT (3-4):    primary keyword + direct variants (actual subject words)
L2 LONG-TAIL (6-8): "[actual subject] ki kahani", "[actual theme] animated", etc.
L3 BROAD (2-3):    "[actual subject] animation", "hindi animated story", "[actual type] cartoon"
L4 RELATED (3-4):  similar topics ONLY if genuinely related
L5 BRAND (2):      "melotoons", "melotoons shorts"

⚠️ Every tag must relate to ACTUAL video content. No guessing. No defaults.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — SETTINGS + EXTRAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
video_category: Film & Animation | Education | Entertainment | Pets & Animals | Comedy (video se match)
video_language: Hindi | Urdu | English (jo video mein bola gaya)
hook_script: pehle 3 sec EXACT hook
pinned_comment: engagement sawaal
thumbnail_text: 2-4 bold words (actual subject)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL CHECK (return se pehle)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [ ] Kya koi bhi title mein aisa word hai jo transcript/visuals mein NAHI tha? → Fix karo
  [ ] primary_keyword saarey 5 titles ke first 40 chars mein?
  [ ] primary_keyword description line 1 mein EXACT?
  [ ] primary_keyword tags[0] mein?
  [ ] Titles 40-60 chars?
  [ ] Description 150+ words?
  [ ] Hashtags exactly 3?
  [ ] Tags 400-480 chars?
  [ ] roman-urdu mode mein koi Devanagari nahi?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON OUTPUT (sirf yeh, koi aur text nahi)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "detected_language": "english|roman-urdu|hindi",
  "video_category": "Film & Animation",
  "video_language": "Hindi|Urdu|English",
  "primary_keyword": "exact search phrase (3-5 words)",
  "content_summary": "1 line — video mein kya hai",
  "detected_subject": "character/topic",
  "niche_fit": "strong|ok|weak",
  "warning": "agar weak to wajah, warna ''",
  "titles": ["T1", "T2", "T3", "T4", "T5"],
  "description": "full SEO description — line1 + variations + chapters(0:00/0:05/0:45) + question + CTA + 3 hashtags",
  "hashtags": ["TopicTag", "Shorts", "NicheTag"],
  "tags": ["primary keyword", "long tail phrase", "... 20-30 tags, 400-480 chars, NO #"],
  "hook_script": "pehle 3 sec exact hook",
  "pinned_comment": "engagement question",
  "thumbnail_text": "2-4 bold words",
  "thumbnail_tip": "1 line thumbnail tip",
  "hook_tip": "1 line opening frame tip"
}
"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        # ```json ... ``` fence hatao
        raw = raw.split("```", 2)[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    raw = raw.strip().strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Aam LLM JSON galtiyan theek karo: trailing commas + smart quotes
        fixed = re.sub(r",(\s*[}\]])", r"\1", raw)
        fixed = fixed.replace("“", '"').replace("”", '"').replace("’", "'")
        return json.loads(fixed)


LANG_MODES = {"auto", "english", "roman-urdu", "hindi"}


def analyze_video(path: str, extra_hint: str = "", lang_pref: str = "auto",
                  use_transcript: bool = True, log=print) -> dict:
    """Video file -> metadata dict. Raises AnalyzerError on failure.

    lang_pref: auto | english | roman-urdu | hindi  (title/desc/hook ki zubaan).
    use_transcript: True -> Whisper se asli script+language nikaal kar Gemini ko deta hai.
    """
    if not Path(path).exists():
        raise AnalyzerError(f"File nahi mili: {path}")

    lang_pref = (lang_pref or "auto").strip().lower()
    if lang_pref not in LANG_MODES:
        lang_pref = "auto"

    # Wrap log to survive Windows cp1252 encoding errors (Devanagari/emoji in output)
    _raw_log = log
    def log(msg):
        try:
            _raw_log(str(msg))
        except (UnicodeEncodeError, UnicodeDecodeError, OSError):
            pass

    # 1) Whisper + Frames PARALLEL — dono ek saath chalao
    import concurrent.futures as _cf

    tr = None
    visual_desc = ""

    _whisper_status = {"msg": "", "ok": False}

    def _run_whisper():
        if not use_transcript:
            _whisper_status["msg"] = "skip"
            return None
        try:
            from . import transcribe as _tr
            _msgs = []
            def _wlog(x):
                _msgs.append(x)
                log(x)
            r = _tr.transcribe(path, log=_wlog)
            if r and r.get("text"):
                _whisper_status["ok"] = True
                _whisper_status["msg"] = f"OK {len(r['text'])} chars lang={r.get('language','?')}"
            else:
                last = [m for m in _msgs if "[whisper]" in m]
                _whisper_status["msg"] = last[-1] if last else "no_result"
            return r
        except Exception as e:
            _whisper_status["msg"] = str(e)[:100]
            log(f"[analyzer] transcript skip: {str(e)[:80]}")
            return None

    def _run_frames():
        try:
            from . import frames as _fr
            frms = _fr.extract_frames(path, n=5, log=log)
            if frms:
                return _fr.frames_to_description(frms, log=log)
        except Exception as e:
            log(f"[analyzer] frames skip: {str(e)[:80]}")
        return ""

    with _cf.ThreadPoolExecutor(max_workers=2) as ex:
        f_tr = ex.submit(_run_whisper)
        f_fr = ex.submit(_run_frames)
        tr = f_tr.result()
        visual_desc = f_fr.result() or ""

    # 2) Effective language — Whisper ka detection use karo (Auto mode mein)
    eff_lang = lang_pref
    has_audio = bool(tr and tr.get("text"))
    if lang_pref == "auto":
        if has_audio and tr.get("language"):
            from . import transcribe as _tr_mod
            eff_lang = _tr_mod.suggested_mode(tr["language"])
            log(f"[analyzer] audio language: {tr['language']} -> {eff_lang}")
        else:
            eff_lang = "roman-urdu"

    # No-audio: visual se keyword extract karo
    if not has_audio and visual_desc:
        try:
            from . import frames as _fr_mod
            vis_kw = _fr_mod.extract_visual_keyword(visual_desc, eff_lang)
            if vis_kw:
                log(f"[analyzer] visual keyword: '{vis_kw}'")
                if not extra_hint.strip():
                    extra_hint = vis_kw
        except Exception:
            pass

    # 3) Prompt banao — VIDEO CONTENT PEHLE, rules baad mein (LLM actual content ko prioritize kare)
    import uuid as _uuid
    req_id = _uuid.uuid4().hex[:12]  # Groq cache break karne ke liye — har request unique

    # Pehle VIDEO-SPECIFIC content inject karo
    video_context = f"REQUEST_ID: {req_id}\n\n"
    video_context += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    video_context += "⭐ IS VIDEO KA ACTUAL CONTENT (PEHLE PADHO — YAHI PRIMARY SOURCE HAI)\n"
    video_context += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if has_audio:
        video_context += (
            f"AUDIO TRANSCRIPT (Whisper, language='{tr['language']}') — YEH ASLI SCRIPT HAI:\n"
            f'"""\n{tr["text"][:2500]}\n"""\n\n'
            "↑ Is transcript se EXACT content, characters, story samjho. Generic mat banao.\n"
        )
    else:
        video_context += "⚠️ IS VIDEO MEIN Kोई VOICEOVER NAHI MILA — VISUALS PE DEPEND KARO.\n"

    if visual_desc:
        label = "VIDEO VISUALS (PRIMARY — koi audio nahi)" if not has_audio else "VIDEO VISUALS (supporting context)"
        video_context += (
            f"\n{label}:\n"
            f'"""\n{visual_desc}\n"""\n'
            "↑ Characters, setting, actions, emotions — sab visuals se samjho. Generic mat banao.\n"
        )

    if extra_hint.strip():
        video_context += f"\nEXTRA HINT (user ne bataya): {extra_hint.strip()}\n"

    if not has_audio and not visual_desc:
        video_context += "\n⚠️ KHABARDAAR: Is video ka koi transcript aur koi visual description nahi mila.\nSirf jo kuch pata hai us pe based karo. Results generic ho sakte hain.\n"

    # Ab system prompt attach karo (rules BAAD MEIN)
    prompt = video_context + "\n" + _SYSTEM_PROMPT.replace("{mode}", eff_lang) + f"\n\nLANGUAGE_MODE = {eff_lang}\n"

    import concurrent.futures

    # 4) Pehle LLM chalao — actual primary_keyword pata chale
    log("=" * 60)
    log(f"[DEBUG] has_audio={has_audio}, has_visual={bool(visual_desc)}, extra_hint='{extra_hint[:50]}'")
    log(f"[DEBUG] transcript preview: '{tr['text'][:200] if tr else 'EMPTY'}'")
    log(f"[DEBUG] visual preview: '{visual_desc[:200] if visual_desc else 'EMPTY'}'")
    log("=" * 60)
    log("[analyzer] LLM generating metadata ...")
    try:
        from . import llm as _llm
        data = _llm.generate(prompt, log=log)
    except Exception as e:
        raise AnalyzerError(str(e))
    log(f"[DEBUG] LLM primary_keyword='{data.get('primary_keyword','?')}' subject='{data.get('detected_subject','?')}'")
    log(f"[DEBUG] LLM title[0]='{(data.get('titles') or [''])[0]}'")
    log("=" * 60)

    result = _normalize(data)
    result["transcript"]      = tr["text"] if tr else ""
    result["whisper_language"] = tr["language"] if tr else ""
    result["whisper_status"]   = _whisper_status["msg"]
    result["has_visual"]       = bool(visual_desc)

    # 5) Ab ACTUAL primary_keyword se SEO research karo (relevant keywords aayenge)
    actual_kw = result.get("primary_keyword", "").strip() or extra_hint.strip()
    content_sum = result.get("content_summary", "").strip()

    log(f"[analyzer] SEO research with actual keyword: '{actual_kw}' ...")
    seo_data = {}
    try:
        from . import seo_research as _sr
        seo_data = _sr.full_research(
            primary_keyword=actual_kw,
            content_summary=content_sum,
            language=eff_lang,
            log=log,
        )
    except Exception as e:
        log(f"[seo] skip: {str(e)[:80]}")
        seo_data = {}

    # (result already set above — do NOT call _normalize again)
    # 6) SEO keyword tags + BASE TAGS ko LLM tags mein merge karo
    try:
        llm_tags = result.get("tags", [])
        existing = set(t.lower() for t in llm_tags)

        new_tags = [t for t in seo_data.get("keyword_tags", [])
                    if t.lower() not in existing]
        for w in seo_data.get("competitors", {}).get("common_keywords", []):
            if w.lower() not in existing:
                new_tags.append(w); existing.add(w.lower())

        # Base tags guaranteed — filter only those not already present
        base_tags_to_add = [t for t in _BASE_TAGS if t.lower() not in existing]

        # Priority order:
        #   1. Primary keyword tags (first 4 from LLM — most specific)
        #   2. Base tags (always-on MeloToons tags — MUST be included)
        #   3. Remaining LLM content tags (filtered: max 40 chars — sentences nahi, keywords chahiye)
        #   4. SEO research tags (filtered: max 40 chars)
        primary_tags   = llm_tags[:4]
        content_tags   = [t for t in llm_tags[4:] if len(t) <= 40]
        seo_tags       = [t for t in new_tags      if len(t) <= 40]
        merged = primary_tags + base_tags_to_add + content_tags + seo_tags

        packed, chars = [], 0
        for t in merged:
            add = (", " if packed else "") + t
            if chars + len(add) > 490:
                continue
            packed.append(t); chars += len(add)
        result["tags"] = packed
        result["tags_string"] = ", ".join(packed)
        result["tags_chars"] = len(result["tags_string"])
        log(f"[seo] final tags: {len(packed)} ({result['tags_chars']} chars) [+base_tags guaranteed]")
    except Exception as e:
        log(f"[seo] tag merge skip: {str(e)[:80]}")

    result["base_tags"] = _BASE_TAGS

    # 7) Tag scores (parallel with SEO already done)
    try:
        from . import tag_score as _ts
        result["tag_scores"] = _ts.score_tags_bulk(
            result.get("tags", []),
            language=result.get("detected_language", "roman-urdu"),
            log=log,
        )
    except Exception as e:
        log(f"[tag_score] skip: {str(e)[:60]}")
        result["tag_scores"] = {}

    # 8) Auto-fix — guarantee minimum quality before scoring
    result = _auto_fix(result, log=log)

    # 8) Sab attach karo
    result["search_keywords"]  = seo_data.get("keyword_suggestions", [])
    result["trends"]           = seo_data.get("trends", {})
    result["competitors"]      = seo_data.get("competitors", {})
    result["posting_strategy"] = seo_data.get("posting_strategy", {})
    result["seo"]              = _seo_score(result)
    return result


def _auto_fix(result: dict, log=print) -> dict:
    """LLM ke baad automatic quality fixer — guarantee 70+ score on every check.

    Kya fix karta hai:
    1. Title — keyword pehle 40 chars mein NAHI to prepend karo
    2. Title — 40-60 chars enforce (chhota = expand hint, bada = trim)
    3. Title — emoji NAHI to add karo, 2+ emoji hain to reduce
    4. Description — keyword line 1 mein NAHI to inject karo
    5. Tags — primary keyword first tag NAHI to move/prepend karo
    6. Hashtags — exactly 3, Shorts hamesha, relevant
    """
    kw = (result.get("primary_keyword") or "").strip()
    kw_l = kw.lower()
    kw1 = kw_l.split()[0] if kw_l else ""
    fixes = []

    # ── 1-3) TITLE FIXES ───────────────────────────────────────────
    _EMOTION_EMOJIS = ["😮", "🤔", "😱", "💪", "😍", "🔥", "✨", "😢", "🥺"]
    import unicodedata

    def _emoji_count(s):
        return sum(1 for c in s if unicodedata.category(c) in ("So", "Sm") or
                   ("\U0001F300" <= c <= "\U0001FAFF"))

    def _has_emotion(s):
        return any(c in s for c in "?!") or any(ch.isdigit() for ch in s)

    fixed_titles = []
    for ti, title in enumerate(result.get("titles", [])):
        original = title
        changed = []

        # Fix: keyword not in first 40 chars — EVERY title must have it (any title click = 100% SEO)
        if kw1 and kw1 not in title.lower()[:46]:
            kw_cap = kw.title()
            new_t = f"{kw_cap} — {title}"
            if len(new_t) > 65:
                new_t = f"{kw_cap}: {title[:60-len(kw_cap)]}…"
            title = new_t[:65]
            changed.append("kw-inject")

        # Fix: length — trim if > 65, or too short (< 40) add a hook
        if len(title) > 65:
            title = title[:62] + "…"
            changed.append("trim")
        elif len(title) < 40:
            # Too short — just flag, don't add generic suffix (generic suffix = wrong SEO)
            changed.append("short-title-warning")

        # Fix: no emoji — add one based on emotion
        ec = _emoji_count(title)
        if ec == 0:
            emoji = "😮" if "?" in title or "!" in title else ("💪" if any(d.isdigit() for d in title) else "✨")
            title = title.rstrip() + f" {emoji}"
            changed.append("emoji-add")
        elif ec > 1:
            # Remove extra emojis (keep last one which is usually the best)
            for c in title:
                if _emoji_count(c) > 0:
                    title = title.replace(c, "", 1)
                    if _emoji_count(title) <= 1:
                        break
            changed.append("emoji-trim")

        # Fix: remove # from title
        if "#" in title:
            title = title.replace("#", "").strip()
            changed.append("hash-remove")

        if changed:
            fixes.append(f"title[{ti}]: {', '.join(changed)}")
        fixed_titles.append(title)

    if fixed_titles:
        result["titles"] = fixed_titles

    # ── 4) DESCRIPTION — vidIQ Triple Keyword: tag words in description ──
    desc = result.get("description", "")
    tags = result.get("tags", [])

    # Fix: primary keyword in line 1
    if kw1 and desc and kw1 not in desc.lower()[:130]:
        lines = desc.split("\n")
        if lines:
            lines[0] = f"{kw.title()} — {lines[0]}"
            desc = "\n".join(lines)
            result["description"] = desc
            fixes.append("desc: kw injected in line 1")

    # vidIQ Triple Keyword: inject tags into description
    # YouTube algorithm: jo words title+tags+description teeno mein hain unhe push karta hai
    desc_lower = desc.lower()
    missing_from_desc = []
    # Check all content-specific tags (top 12) + all base tags
    tags_to_check = tags[:12] + [t for t in _BASE_TAGS if t not in tags[:12]]
    for tag in tags_to_check:
        tag_words = tag.lower().split()
        if tag_words and not any(w in desc_lower for w in tag_words if len(w) > 3):
            missing_from_desc.append(tag)

    if missing_from_desc:
        lang = result.get("detected_language", "roman-urdu")
        t = missing_from_desc[:6]
        n = len(t)

        # Natural sentences — keyword stuffing nahi, YouTube-friendly organic text
        if lang == "english":
            if n == 1:
                injection = f"\n\nFans of {t[0]} will especially enjoy this animated short!"
            elif n == 2:
                injection = f"\n\nThis video is a must-watch for {t[0]} and {t[1]} fans."
            elif n <= 4:
                injection = (
                    f"\n\nThis {t[0]} story is perfect for {t[1]} and {t[2]} fans."
                )
                if n == 4:
                    injection += f" {t[3]} lovers will enjoy it too."
            else:
                injection = (
                    f"\n\nThis {t[0]} story blends {t[1]} and {t[2]} into one unforgettable "
                    f"animated short. {t[3]} fans and {t[4]} lovers will especially enjoy this!"
                )
        else:
            if n == 1:
                injection = f"\n\n{t[0]} ke fans ko yeh video zaroor dekhni chahiye!"
            elif n == 2:
                injection = f"\n\n{t[0]} aur {t[1]} ke deewaanon ke liye yeh ek perfect animated kahani hai."
            elif n <= 4:
                mid = " aur ".join([", ".join(t[1:-1]), t[-1]]) if n > 2 else t[1]
                injection = (
                    f"\n\nYeh {t[0]} wali animated kahani {mid} pasand karne walon ke liye bilkul sahi hai."
                )
            else:
                injection = (
                    f"\n\nYeh {t[0]} aur {t[1]} ki kahani un logon ke liye khaas hai jo {t[2]} "
                    f"dekhna pasand karte hain. {t[3]} aur {t[4]} ke shauqeen bhi zaroor enjoy karein!"
                )

        desc = result.get("description", "").rstrip() + injection
        result["description"] = desc
        fixes.append(f"desc: {len(missing_from_desc)} tags injected (natural sentences)")
    # Word count fix — guarantee 150+ words for YouTube full indexing
    lang = result.get("detected_language", "roman-urdu")
    # detected_subject comma list ho sakti hai — sirf pehla clean subject lo
    _raw_subj = result.get("detected_subject", "") or kw
    subject = _raw_subj.split(",")[0].strip() or kw
    desc = result.get("description", "")
    wc = len(desc.split())
    if wc < 150:
        if lang == "english":
            extra = (
                f"\n\nThis video about {subject} is part of the MeloToons channel. "
                f"If you enjoy this {kw} content, please like and subscribe for more. "
                f"Share this video with someone who would appreciate it.\n\n"
                f"MeloToons creates high-quality videos that entertain and inspire. "
                f"Join our growing community and never miss an upload."
            )
        else:
            extra = (
                f"\n\nYeh {subject} video MeloToons channel ka hissa hai. "
                f"Agar yeh {kw} video aapko pasand aaya to like karein aur subscribe karein. "
                f"Apne doston aur family ke saath zaroor share karein.\n\n"
                f"MeloToons pe hum aise videos banate hain jo entertain aur inspire karte hain. "
                f"Hamare channel se jud jaiye aur koi video miss mat kariye."
            )
        result["description"] = desc.rstrip() + extra
        new_wc = len(result["description"].split())
        fixes.append(f"desc: {wc}→{new_wc} words")

    # ── 5) TAGS — primary keyword as first tag ───────────────────
    tags = result.get("tags", [])
    if kw1 and tags and kw1 not in tags[0].lower():
        kw_tags = [t for t in tags if kw1 in t.lower()]
        other = [t for t in tags if kw1 not in t.lower()]
        if kw_tags:
            result["tags"] = kw_tags + other
        else:
            result["tags"] = [kw] + tags
        result["tags_string"] = ", ".join(result["tags"])
        result["tags_chars"]  = len(result["tags_string"])
        fixes.append("tags: kw moved to front")

    # ── 6) HASHTAGS — exactly 3, Shorts hamesha ─────────────────
    hashtags = result.get("hashtags", [])
    # Ensure Shorts is present
    if not any(h.lower() == "shorts" for h in hashtags):
        hashtags.append("Shorts")
        fixes.append("hashtags: Shorts added")
    # Keep exactly 3 (Shorts + 2 topic-specific)
    shorts = [h for h in hashtags if h.lower() == "shorts"]
    others = [h for h in hashtags if h.lower() != "shorts"]
    result["hashtags"] = (others[:2] + shorts)[:3]
    result["hashtags_string"] = " ".join("#" + h for h in result["hashtags"])

    # ── 7) COPYRIGHT — bilkul last mein, hashtags ke baad ────────────
    # Standard YouTube order: hook → content → hashtags → © copyright (bottom)
    import datetime
    year = datetime.datetime.now().year
    desc_final = result.get("description", "")
    cr_line = f"© {year} MeloToons. All Rights Reserved. Unauthorized re-upload, reproduction, or distribution is strictly prohibited."
    if "all rights reserved" not in desc_final.lower():
        result["description"] = desc_final.rstrip() + "\n\n" + cr_line
        fixes.append("copyright added at end")

    if fixes:
        log(f"[autofix] {len(fixes)} fixes: {'; '.join(fixes)}")
    return result


def _normalize(d: dict) -> dict:
    """Missing fields ko safe defaults se bhar do."""
    titles = d.get("titles") or []
    if isinstance(titles, str):
        titles = [titles]
    tags = d.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("#", "").split(",") if t.strip()]
    # tags clean + dedupe (# hatao — YouTube tags field mein hash nahi lagta)
    seen, clean = set(), []
    for t in tags:
        t = str(t).strip().lstrip("#").strip().lower()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    # YouTube tags field ki 500-char limit tak PROPERLY pack karo
    # Target: 400-480 chars. Small tags skip nahi karo — saare fit karo, phir fill karo.
    packed, cur = [], 0
    for t in clean:
        comma = 2 if packed else 0
        if cur + comma + len(t) <= 490:
            packed.append(t)
            cur += comma + len(t)
    tags_str = ", ".join(packed)

    # hashtags (tags se ALAG — # ke saath, title/description ke liye)
    raw_hash = d.get("hashtags") or []
    if isinstance(raw_hash, str):
        raw_hash = [h for h in raw_hash.replace("#", " ").split() if h.strip()]
    seen_h, hashtags = set(), []
    for h in raw_hash:
        h = str(h).strip().lstrip("#").replace(" ", "")
        if h and h.lower() not in seen_h:
            seen_h.add(h.lower())
            hashtags.append(h)
    hashtags = hashtags[:3]   # vidIQ rule: exactly 3

    out = {
        "detected_language": d.get("detected_language", ""),
        "video_category": str(d.get("video_category", "")).strip(),
        "video_language": str(d.get("video_language", "")).strip(),
        "primary_keyword": str(d.get("primary_keyword", "")).strip(),
        "content_summary": d.get("content_summary", ""),
        "detected_subject": d.get("detected_subject", ""),
        "niche_fit": d.get("niche_fit", "ok"),
        "warning": d.get("warning", ""),
        "titles": [str(t).strip() for t in titles if str(t).strip()][:5],
        "description": d.get("description", "").strip(),
        "hashtags": hashtags,
        "hashtags_string": " ".join("#" + h for h in hashtags),
        "tags": packed,
        "tags_string": tags_str,
        "tags_chars": len(tags_str),
        "hook_script": str(d.get("hook_script", "")).strip(),
        "pinned_comment": str(d.get("pinned_comment", "")).strip(),
        "thumbnail_text": str(d.get("thumbnail_text", "")).strip(),
        "thumbnail_tip": d.get("thumbnail_tip", ""),
        "hook_tip": d.get("hook_tip", ""),
    }
    # Safety check + auto-fix: roman-urdu mode mein Devanagari → transliterate via Groq
    _deva_re = re.compile(r'[ऀ-ॿ؀-ۿ]')  # Devanagari + Arabic/Nastaliq
    out["script_warning"] = ""
    if out.get("detected_language") == "roman-urdu":
        deva_titles = [t for t in out.get("titles", []) if _deva_re.search(t)]
        deva_desc = _deva_re.search(out.get("description", ""))
        if deva_titles or deva_desc:
            # Auto-transliterate using Groq
            try:
                from . import llm as _llm_mod
                _texts = out.get("titles", []) + [out.get("description", "")[:500]]
                _fix_prompt = (
                    "Convert these Hindi/Urdu texts to ROMAN URDU (Latin script only, a-z). "
                    "No Devanagari, no Arabic script. Natural readable Roman Urdu. "
                    "Return JSON: {\"titles\": [...], \"description_start\": \"...\"}\n"
                    f"Titles: {out.get('titles', [])}\n"
                    f"Description start: {out.get('description','')[:300]}"
                )
                _fixed = _llm_mod.generate(_fix_prompt)
                if _fixed.get("titles"):
                    out["titles"] = [str(t) for t in _fixed["titles"]]
                if _fixed.get("description_start"):
                    _desc = out.get("description", "")
                    _new_start = str(_fixed["description_start"])
                    # Replace first 300 chars of description
                    out["description"] = _new_start + _desc[300:]
            except Exception as e:
                out["script_warning"] = f"⚠️ Roman Urdu convert nahi hua ({str(e)[:60]}). Manually check karo."

    # seo score baad mein (keyword enrichment ke baad) lagaya jayega
    return out


def _seo_score(d: dict) -> dict:
    """vidIQ Boost-level SEO score — 100/100 achievable.

    vidIQ research-based weightage:
      Title Optimization   : 25 pts
      Description SEO      : 25 pts
      Tags Quality         : 20 pts
      Keyword Consistency  : 20 pts  ← vidIQ Triple Keyword Rule
      Hashtags + Settings  : 10 pts
    Total = 100
    """
    title   = (d["titles"][0] if d.get("titles") else "")
    title_l = title.lower()
    desc    = (d.get("description") or "")
    desc_l  = desc.lower()
    kw      = (d.get("primary_keyword") or "").lower().strip()
    kw1     = kw.split()[0] if kw else ""   # first word of keyword
    tags    = d.get("tags") or []
    tc      = d.get("tags_chars") or len(", ".join(tags))
    hashes  = d.get("hashtags") or []
    first125 = desc_l[:130]
    wc      = len(desc.split())

    # helper: kw in text (partial match ok — first word at least)
    def _kw(text): return bool(kw1) and kw1 in text.lower()

    # ── TITLE (25 pts) ──────────────────────────────────────────────
    t_checks = [
        ("Keyword title ke pehle 40 chars mein",    bool(kw) and kw1 in title_l[:45],          10),
        ("Title lambai 40-60 chars (mobile safe)",  40 <= len(title) <= 65,                     7),
        ("Emotion/curiosity hook (? ya ! ya number)", any(c in title for c in "?!") or
                                                     any(c.isdigit() for c in title),            5),
        ("Title saaf — koi # nahi",                 "#" not in title,                            3),
    ]
    t_pts = sum(w for _, ok, w in t_checks if ok)

    # ── DESCRIPTION (25 pts) ────────────────────────────────────────
    d_checks = [
        ("Keyword description LINE 1 mein (~125 chars)", _kw(first125),                         12),
        ("Description 150+ words (YouTube indexing)",   wc >= 150,                               7),
        ("Engagement sawaal (comment trigger)",         "?" in desc,                              4),
        ("CTA — Like + Subscribe",                     any(w in desc_l for w in
                                                        ("subscribe", "like", "bell")),            2),
    ]
    d_pts = sum(w for _, ok, w in d_checks if ok)

    # ── TAGS (20 pts) ───────────────────────────────────────────────
    tg_checks = [
        ("Pehla tag = primary keyword (EXACT/CLOSE)", bool(kw1) and bool(tags) and
                                                      kw1 in tags[0].lower(),                   10),
        ("Tags 400-480 chars (500-char limit ka fayda)", 380 <= tc <= 500,                        6),
        ("20+ relevant tags (vidIQ recommends 15-30)",  len(tags) >= 15,                          4),
    ]
    tg_pts = sum(w for _, ok, w in tg_checks if ok)

    # ── KEYWORD CONSISTENCY — vidIQ Triple Keyword (20 pts) ─────────
    # vidIQ formula: SAME keywords in TITLE + TAGS + DESCRIPTION (all 3 places)
    kw_title = bool(kw1) and kw1 in title_l[:45]
    kw_desc  = _kw(first125)
    kw_tag   = bool(kw1) and bool(tags) and kw1 in tags[0].lower()
    # Extra: tag keywords appearing in description body (vidIQ "5 keywords in desc" check)
    tags_in_desc_count = sum(1 for t in tags[:10]
                             if any(w in desc_l for w in t.lower().split() if len(w)>3))
    triple   = sum([kw_title, kw_desc, kw_tag])
    kw_checks = [
        ("Triple Keyword: Title mein (primary keyword)", kw_title, 7),
        ("Triple Keyword: Description line 1 mein",      kw_desc,  7),
        ("Triple Keyword: First tag mein",                kw_tag,   3),
        ("Tag keywords description mein bhi (vidIQ check)", tags_in_desc_count >= 3, 3),
    ]
    kw_pts = sum(w for _, ok, w in kw_checks if ok)

    # ── HASHTAGS + SETTINGS (10 pts) ────────────────────────────────
    h_checks = [
        ("Hashtags exactly 3 (YouTube rule)",
         len(hashes) == 3, 4),
        ("#Shorts include kiya",
         any("shorts" == h.lower() for h in hashes) or "#shorts" in desc_l, 3),
        ("Category + Language set ki",
         bool(d.get("video_category")) and bool(d.get("video_language")), 3),
    ]
    h_pts = sum(w for _, ok, w in h_checks if ok)

    total = t_pts + d_pts + tg_pts + kw_pts + h_pts

    def _fmt(checks):
        return [{"label": lbl, "ok": bool(ok), "pts": w} for lbl, ok, w in checks]

    return {
        "score": total,
        "grade": ("🟢 Excellent — 100% SEO" if total >= 95 else
                  "🟢 Very Good" if total >= 85 else
                  "🟡 Good" if total >= 70 else
                  "🟠 Needs Work" if total >= 50 else "🔴 Poor"),
        "triple_keyword": triple,   # 0,1,2,3 — 3 = perfect
        "breakdown": {
            "title":       {"score": t_pts,  "max": 25, "checks": _fmt(t_checks)},
            "description": {"score": d_pts,  "max": 25, "checks": _fmt(d_checks)},
            "tags":        {"score": tg_pts, "max": 20, "checks": _fmt(tg_checks)},
            "keyword_consistency": {"score": kw_pts, "max": 20, "checks": _fmt(kw_checks)},
            "hashtags":    {"score": h_pts,  "max": 10, "checks": _fmt(h_checks)},
        },
    }
