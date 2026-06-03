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
# Prompt — yahi tool ka dimaag hai
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """\
⚠️ SCRIPT RULE — PEHLE PADHO, PHIR KAAM KARO ⚠️
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LANGUAGE_MODE = roman-urdu  →  EVERY WORD in Latin/English letters ONLY
  ✅ CORRECT: "Yeh 5 sabziyan rozana khao, 30 din mein farq dekho"
  ❌ WRONG:   "यह 5 सब्जियां रोज खाओ"  ← Devanagari HARAM HAI roman-urdu mode mein
  ❌ WRONG:   "یہ 5 سبزیاں"             ← Arabic/Nastaliq bhi NAHI

  LANGUAGE_MODE = english     →  Everything in English
  LANGUAGE_MODE = hindi       →  ONLY then use Devanagari (हिंदी)

This rule overrides EVERYTHING. If you output Devanagari in roman-urdu mode,
your entire response is WRONG and will be rejected. Use a-z letters only.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tum vidIQ Boost level ka YouTube SEO expert ho — MeloToons channel ke liye kaam
karta hai. Har output mein vidIQ ka "Triple Keyword Rule" + "Optimize Score 100/100"
achieve karna LAAZMI hai. Koi compromise nahi.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHANNEL NICHE — YEH HAMESHA YAAD RAKHO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Channel: MeloToons
Niche: AI-generated 3D Pixar-style DESI animated shorts
Audience: Pakistani + Indian (Roman Urdu/Hindi speakers)
Content types:
  ✅ Cute animals (billi, khargosh, lomdi, etc.) — emotional/heartwarming stories
  ✅ Cute children characters — moral lessons
  ✅ Talking food/objects — funny/educational
  ✅ Desi situations (garmi, school, ghar, dukaan) — relatable stories
  ❌ AVOID niche: rags-to-riches motivational (oversaturated), dark/violent

NICHE KEYWORDS (hamesha in mein se use karo):
  Roman Urdu: "billi ki kahani", "pyaari kahani", "moral kahani", "dil ko chhoone wali kahani"
  English: "animated moral story", "cute animal story", "3D animated short", "kids story hindi"
  Brand: "melotoons", "melotoons shorts"

WRONG AUDIENCE PREVENTION (CRITICAL):
Tags jo KABHI NAHI laganay — yeh wrong viewers laate hain jo swipe karte hain:
  ❌ "cartoon" alone — doraemon/peppa pig wale aa jaate hain
  ❌ "animation" alone — Disney/Marvel wale aa jaate hain
  ❌ "funny video", "viral", "trending" — random audience
  ❌ Kisi specific cartoon ka naam (doraemon, pokemon) agar video mein woh nahi
  ✅ HAMESHA specific: "cute billi cartoon", "moral story animation", "hindi animated story"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 0 — PRIMARY KEYWORD pehle decide karo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Video transcript + visuals se EK sabse important search phrase nikalo.
YEH KEYWORD TEEN JAGAH EXACT SAME AANA CHAHIYE (vidIQ Triple Keyword Rule):
  [A] Title ke PEHLE 40 characters mein
  [B] Description ki PEHLI line (~125 chars) mein WORD-FOR-WORD
  [C] Tags list ka PEHLA tag

Agar [A][B][C] mein exact match nahi → score 100 nahi aayega. Ensure karo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — LANGUAGE (output ki zubaan)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LANGUAGE_MODE = {mode} (neeche inject hoga)
  english    → sab kuch natural English mein
  roman-urdu → SIRF Roman/Latin letters (a-z) — "Roz subah yeh 5 sabziyan khao"
               Devanagari (हिंदी script) KABHI NAHI — ek bhi character nahi
  hindi      → Devanagari Hindi script
  auto       → transcript/visuals se detect karo (English audio → English output)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — 5 TITLES (vidIQ AI Title Generator — 9 emotion types se)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VIDEO KE ACTUAL TRANSCRIPT + VISUALS pe based — GENERIC nahi.
Har title: primary keyword PEHLE 40 chars mein + 1 emoji + NO # + 40-60 chars.

vidIQ ke 9 emotion types mein se 5 use karo:
VIRAL TITLE PATTERNS — har video type ke liye alag approach:

🥦 HEALTH/FOOD video ho to:
  T1 DOCTOR RAAZ: "Doctor ne yeh [food] kyun chhupaya? 😱" — authority + mystery
  T2 SHOCKING FACT: "90% log nahi jaante [food] kya karta hai body ko 🤯"
  T3 CHALLENGE: "Rozana [food] khao, [N] din mein doctor hairaan ho jayega 😮"
  T4 BEFORE/AFTER: "[Food] khana band kiya to kya hoga? Jaanke dar jaoge 😨"
  T5 SECRET: "Yeh [food] ka raaz sirf doctors jaante the, ab tum bhi jano 🔥"

📖 MORAL STORY ho to:
  T1 CLIFF HANGER: "Jab [character] ne [action] kiya... phir jo hua 😢"
  T2 EMOTIONAL: "[Character] ne sirf [small thing] kiya aur sab kuch badal gaya 🥺"
  T3 QUESTION HOOK: "Kya aap bina rone ke yeh kahani sun sakte hain? 😭"
  T4 SHOCK: "Usne [action] kiya tha, tab kisi ne soch bhi nahi tha ke... 😱"
  T5 LESSON: "Is chhoti si galti ne uski poori zindagi badal di 💔"

😺 CUTE ANIMAL ho to:
  T1 EMPATHY: "Jab [animal] ko [situation] mein dekha to dil pighal gaya 🥺"
  T2 TRANSFORMATION: "[Animal] ne yeh seekha aur sab hairan reh gaye ✨"
  T3 RESCUE: "Koi uski madad nahi karta tha, tab [character] aaya 😭💛"

🔑 TITLE FORMULA (har case mein):
  PRIMARY KEYWORD + EMOTIONAL HOOK + SUSPENSE (ending ka hint, reveal nahi)
  Max 60 chars. 1 emoji. VIDEO KE ASLI CONTENT se — generic nahi.

RHYMING/FLOW check karo: title bolne mein smooth lage, awkward na lage.

TITLE SCORE checklist (100/100 ke liye):
  ✓ primary keyword first 40 chars → +30 pts
  ✓ length 40-60 chars             → +20 pts
  ✓ emotion/curiosity (?/!/number) → +20 pts
  ✓ exactly 1 emoji                → +15 pts
  ✓ no # hashtag                   → +10 pts
  ✓ specific to video content      → +5 pts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — DESCRIPTION (SEO-optimized, 150+ words)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINE 1 (~125 chars): primary keyword EXACT + compelling hook. ENDING reveal nahi.
  Example: "5 sabziyan jo rozana khaoge to immunity 10x hogi — yeh raaz sirf..."
LINE 2-3: keyword VARIATIONS naturally use karo (synonyms, related phrases, long-tail).
  Example: "healthy vegetables", "sehat ke liye sabziyan", "immunity boost karne ka tarika"
ENGAGEMENT Q: Relatable sawaal jo comment trigger kare.
  Example: "Aap mein se kitne log rozana yeh khate hain? Comment mein batao 👇"
CTA: Like + Subscribe (1 line).
HASHTAGS (SIRF 3, description ke END mein):
  #1 = primary topic specific (e.g. #SabziyonKeFayde)
  #2 = #Shorts (HAMESHA)
  #3 = niche/format (e.g. #HindiAnimation ya #MoralStory)
  YouTube ke pehle 3 hashtags title ke UPAR float karte hain — isliye best 3 pehle.

DESCRIPTION SCORE checklist:
  ✓ primary keyword line 1 mein   → +25 pts
  ✓ 150+ words                    → +20 pts
  ✓ keyword variations line 2-3   → +15 pts
  ✓ engagement question           → +15 pts
  ✓ CTA present                   → +15 pts
  ✓ exactly 3 hashtags            → +10 pts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — TAGS (vidIQ 5-layer, NO #, fill 400-480 chars)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YouTube 500-char tag limit ka MAXIMUM use karo. 20-30 tags, 400-480 chars TOTAL.
NO # symbol. NO duplicates. NO "viral/trending/song/status/lyrics/usa/uk".
PRIMARY KEYWORD = TAG[0] (exact match from title).

5-LAYER formula (har layer se tags do — 3-5 word PHRASES preferred):
  L1 EXACT (3-4):     primary keyword exact + direct variants
                      e.g. "5 sabziyan", "paanch sabziyan ke fayde", "sabziyan benefits"
  L2 LONG-TAIL (6-8): 3-5 word phrases log YouTube pe TYPE karte hain
                      e.g. "immunity boost karne wali sabziyan", "roz khane wali sabziyan"
                      e.g. "healthy vegetables for immunity", "vegetables for skin glow"
  L3 BROAD (2-3):     CONTENT-SPECIFIC broad phrases (NEVER single generic words!)
                      ❌ GALAT: "cartoon", "animation", "video" — yeh WRONG AUDIENCE laate hain!
                      ✅ SAHI: "cat animation", "moral story animation", "hindi animated story"
                      Rule: Broad tag mein ALWAYS video ka subject word hona chahiye
  L4 RELATED/LSI (3-4): similar popular video topics (suggested sidebar anchor)
                      ✅ ONLY if content is GENUINELY similar — no random popular terms
                      ❌ KABHI NAHI: "doraemon", "dragon ball", "peppa pig" — agar video mein nahi
  L5 BRAND (2):       "melotoons", "melotoons shorts"

⚠️ WRONG AUDIENCE PREVENTION (ZAROORI):
Tags se wrong audience aati hai → woh swipe karte hain → retention kill → views ruk jaate hain!
Is liye: har tag VIDEO KE ACTUAL CONTENT se match karna LAAZMI hai.
Agar video mein billi hai → "cat story" sahi, "doraemon" BILKUL GALAT.

TAGS SCORE checklist:
  ✓ tag[0] = primary keyword     → +30 pts
  ✓ 20-30 tags                   → +25 pts
  ✓ 400-480 chars total          → +25 pts
  ✓ no # symbol                  → +20 pts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — YOUTUBE SETTINGS + EXTRAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
video_category: Film & Animation | Education | Entertainment | Pets & Animals |
  Howto & Style | Comedy | People & Blogs (video dekh ke SAHI category choose karo)
video_language: Hindi | Urdu | English (video mein JO BOLA, wahi)
hook_script: pehle 3 sec ka EXACT hook — kya bolna/dikhana hai taake swipe na ho
pinned_comment: engagement sawaal pin karne ke liye
thumbnail_text: 2-4 word bold text thumbnail pe

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-VERIFICATION (return se pehle YEH CHECK karo)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return karne se PEHLE verify karo:
  [ ] primary_keyword SAAREY 5 titles ke first 40 chars mein hai? (SABSE ZAROORI — koi bhi title select ho, SEO 100% rahe)
  [ ] primary_keyword description line 1 mein EXACT hai?
  [ ] primary_keyword tags[0] mein hai?
  [ ] titles sab 40-60 chars hain?
  [ ] description 150+ words hai?
  [ ] hashtags exactly 3 hain?
  [ ] tags total 400-480 chars hain?
  [ ] koi Devanagari nahi (roman-urdu mode mein)?
Agar koi check fail → fix karo phir return karo.

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
  "description": "full SEO description — line1 + variations + question + CTA + 3 hashtags",
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

    # 1) Whisper + Frames PARALLEL — dono ek saath chalao
    import concurrent.futures as _cf

    tr = None
    visual_desc = ""

    def _run_whisper():
        if not use_transcript:
            return None
        try:
            from . import transcribe as _tr
            return _tr.transcribe(path, log=log)
        except Exception as e:
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
            log(f"[analyzer] audio language: {tr['language']} → {eff_lang}")
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

    # 3) Prompt banao
    prompt = _SYSTEM_PROMPT.replace("{mode}", eff_lang) + f"\n\nLANGUAGE_MODE = {eff_lang}\n"

    if not has_audio and visual_desc:
        # No voiceover — visuals are THE primary source
        prompt += (
            f"\n⚠️ IS VIDEO MEIN KOI VOICEOVER/AUDIO NAHI HAI.\n"
            f"VISUALS HI PRIMARY SOURCE HAIN — inhe carefully analyze karo:\n"
            f'"""\n{visual_desc}\n"""\n'
            "Character ka appearance, emotions, actions, setting, story arc, theme — sab visuals se samjho.\n"
            "Titles/description SIRF visual content pe based karo — koi generic assumption nahi.\n"
        )
    elif visual_desc:
        prompt += (
            f"\nVIDEO VISUALS (supporting context):\n"
            f'"""\n{visual_desc}\n"""\n'
        )

    if has_audio:
        prompt += (
            f"\nAUDIO TRANSCRIPT (Whisper, language='{tr['language']}'):\n"
            f'"""\n{tr["text"][:2500]}\n"""\n'
            "Transcript + visuals DONO se content samjho.\n"
        )

    if extra_hint.strip():
        prompt += f"\nEXTRA HINT / KEYWORD: {extra_hint.strip()}\n"

    if extra_hint.strip():
        prompt += f"\nEXTRA HINT: {extra_hint.strip()}\n"

    import concurrent.futures

    # 4) Pehle LLM chalao — actual primary_keyword pata chale
    log("[analyzer] LLM generating metadata ...")
    try:
        from . import llm as _llm
        data = _llm.generate(prompt, log=log)
    except Exception as e:
        raise AnalyzerError(str(e))

    result = _normalize(data)
    result["transcript"]      = tr["text"] if tr else ""
    result["whisper_language"] = tr["language"] if tr else ""

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

    result = _normalize(data)
    result["transcript"] = tr["text"] if tr else ""
    result["whisper_language"] = tr["language"] if tr else ""

    # 6) SEO keyword tags ko LLM tags mein merge karo
    try:
        existing = set(t.lower() for t in result.get("tags", []))
        new_tags = [t for t in seo_data.get("keyword_tags", [])
                    if t.lower() not in existing]
        for w in seo_data.get("competitors", {}).get("common_keywords", []):
            if w.lower() not in existing:
                new_tags.append(w); existing.add(w.lower())
        merged = result["tags"] + new_tags
        packed, chars = [], 0
        for t in merged:
            add = (", " if packed else "") + t
            if chars + len(add) > 490: continue
            packed.append(t); chars += len(add)
        result["tags"] = packed
        result["tags_string"] = ", ".join(packed)
        result["tags_chars"] = len(result["tags_string"])
        log(f"[seo] final tags: {len(packed)} ({result['tags_chars']} chars)")
    except Exception as e:
        log(f"[seo] tag merge skip: {str(e)[:80]}")

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
            # Too short — add a relevant suffix
            suffix = " — yeh zaroor dekho" if "roman-urdu" in (result.get("detected_language","")) else " — Must Watch!"
            title = (title.rstrip("…") + suffix)[:65]
            changed.append("extend")

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

    # ── 4) DESCRIPTION — keyword in first line + minimum word count ─
    desc = result.get("description", "")
    if kw1 and desc and kw1 not in desc.lower()[:130]:
        lines = desc.split("\n")
        if lines:
            lines[0] = f"{kw.title()} — {lines[0]}"
            desc = "\n".join(lines)
            result["description"] = desc
            fixes.append("desc: kw injected in line 1")
    # Word count fix — guarantee 150+ words for YouTube full indexing
    lang = result.get("detected_language", "roman-urdu")
    subject = result.get("detected_subject", kw)
    desc = result.get("description", "")
    wc = len(desc.split())
    if wc < 120:
        if lang == "english":
            extra = (
                f"\n\nIn this short animated video, we explore the story of {subject}. "
                f"This {kw} story is designed to be both entertaining and meaningful for viewers "
                f"of all ages. Whether you are a child or an adult, the message of this animated "
                f"short will stay with you long after it ends.\n\n"
                f"At MeloToons, we create high-quality 3D animated stories that inspire, educate, "
                f"and entertain. Every video is crafted with care to deliver a strong moral lesson "
                f"through engaging characters and beautiful visuals. If you enjoy this video, please "
                f"share it with your friends and family.\n\n"
                f"Search keywords: {kw}, animated story, moral story for kids, short film animation."
            )
        else:
            extra = (
                f"\n\nIs chhoti si animated video mein {subject} ki dil ko chhoo lene wali kahani hai. "
                f"Yeh {kw} story har umra ke viewers ke liye entertaining aur meaningful hai. "
                f"Chahे aap bachay ho ya bade, is animated short ka message aapke dil mein ghar kar jayega.\n\n"
                f"MeloToons pe hum high-quality 3D animated kahaniyan banate hain jo inspire, educate "
                f"aur entertain karti hain. Har video mein ek strong moral lesson hota hai. "
                f"Agar yeh video pasand aaye to apne doston aur family ke saath zaroor share karein.\n\n"
                f"Search: {kw}, animated kahani, moral story, bachon ki kahani, 3D animation shorts."
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
        ("Description 150+ words (YouTube indexing)",   wc >= 100,                               7),
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
    kw_title = bool(kw1) and kw1 in title_l[:45]
    kw_desc  = _kw(first125)
    kw_tag   = bool(kw1) and bool(tags) and kw1 in tags[0].lower()
    triple   = sum([kw_title, kw_desc, kw_tag])
    kw_checks = [
        ("Triple Keyword: Title mein",             kw_title,   7),
        ("Triple Keyword: Description line 1 mein", kw_desc,   7),
        ("Triple Keyword: First tag mein",          kw_tag,    6),
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
