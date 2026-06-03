"""MeloToons Title Generator — video upload karo, viral title/description/tags lo.

Chalao:  python app.py   (phir browser khud khulega:  http://127.0.0.1:5055)
"""

from __future__ import annotations

import os
import threading
import traceback
import uuid
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()  # .env se GEMINI_API_KEY

from core import analyzer  # noqa: E402

BASE = Path(__file__).resolve().parent
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB


@app.route("/")
def index():
    from core.llm import available_providers
    providers = ", ".join(available_providers()) or "None"
    return render_template("index.html", configured=analyzer.is_configured(), providers=providers)


@app.route("/generate", methods=["POST"])
def generate():
    if "video" not in request.files:
        return jsonify({"ok": False, "error": "Koi video file nahi mili."}), 400
    file = request.files["video"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Video select karein."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED:
        return jsonify({"ok": False, "error": f"Format support nahi: {ext}. mp4/mov/webm daalein."}), 400

    if not analyzer.is_configured():
        return jsonify({"ok": False, "error": "GEMINI_API_KEY set nahi hai (.env file check karein)."}), 400

    hint = (request.form.get("hint") or "").strip()
    lang = (request.form.get("lang") or "auto").strip().lower()
    skip_tr = request.form.get("skip_tr") == "1"
    tmp = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    file.save(tmp)

    try:
        result = analyzer.analyze_video(str(tmp), extra_hint=hint, lang_pref=lang,
                                        use_transcript=not skip_tr)
        return jsonify({"ok": True, "result": result})
    except analyzer.AnalyzerError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Unexpected: {e}"}), 500
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/refresh_titles", methods=["POST"])
def refresh_titles():
    """Same video ke liye naye 5 titles generate karo (no re-upload needed)."""
    data = request.get_json() or {}
    keyword   = (data.get("keyword") or "").strip()
    language  = (data.get("language") or "roman-urdu").strip()
    summary   = (data.get("summary") or "").strip()
    transcript = (data.get("transcript") or "").strip()[:1000]
    subject   = (data.get("subject") or keyword).strip()
    niche     = (data.get("niche") or "").strip()

    if not keyword:
        return jsonify({"ok": False, "error": "Keyword missing"}), 400

    lang_rule = {
        "english":    "Write ONLY in natural English.",
        "roman-urdu": "Write ONLY in Roman Urdu/Hindi (Latin a-z letters). NO Devanagari, NO Arabic script.",
        "hindi":      "Write in Devanagari Hindi script.",
    }.get(language, "Write in Roman Urdu/Hindi (Latin letters only).")

    # Also pass existing description/tags context for consistency
    existing_desc = (data.get("description") or "").strip()[:300]
    existing_tags = data.get("existing_tags") or []
    tags_str = ", ".join(existing_tags[:8]) if existing_tags else ""

    # Get first tag as the exact keyword anchor
    first_tag = existing_tags[0] if existing_tags else keyword

    prompt = f"""You are a viral YouTube Shorts title expert. Generate 5 DIFFERENT titles for the SAME video.

⚠️ CRITICAL RULE — READ BEFORE GENERATING:
ALL 5 titles MUST contain this EXACT keyword (or 1-2 word variant) in the FIRST 40 characters:
  PRIMARY KEYWORD: "{keyword}"
  FIRST TAG: "{first_tag}"

This is mandatory because the description and tags are already set with this keyword.
If a title does NOT have this keyword near the start → it will FAIL the SEO score.

VIDEO INFO:
- Primary keyword: {keyword}
- Content: {summary}
- Subject: {subject}
- Existing tags: {tags_str}
- Description start: {existing_desc[:200]}

LANGUAGE RULE: {lang_rule}

RULES FOR ALL 5 TITLES:
1. PRIMARY KEYWORD "{keyword}" → MUST be in FIRST 40 chars of EVERY title (non-negotiable)
2. 5 DIFFERENT emotional hooks: curiosity / shock / number+benefit / question / emotion
3. Length: 40-60 chars each
4. Exactly 1 emoji per title, NO hashtags (#)
5. Same TOPIC as tags and description — different ANGLE only

GOOD examples (all use keyword, different hooks):
  CURIOSITY: "{keyword} — yeh sach jaankar hairaan ho jaoge 😱"
  SHOCK: "90% log nahi jaante {keyword} ka raaz 🤯"
  NUMBER: "{keyword} ke 5 fayde jo doctor bhi chhupate hain 💪"
  QUESTION: "Kya aap jaante hain {keyword} kya karta hai body ko? 🤔"
  EMOTION: "Jab {keyword} ki kahani suni to sab ro pade 🥺"

Return ONLY JSON array: ["title1","title2","title3","title4","title5"]
"""
    try:
        from core import llm as _llm
        import json
        raw = _llm.generate(prompt + '\nReturn JSON array only: ["t1","t2","t3","t4","t5"]')
        # Extract titles from result
        if isinstance(raw, list):
            titles = [str(t).strip() for t in raw if str(t).strip()][:5]
        elif isinstance(raw, dict):
            for k in ["titles", "title", "result", "data"]:
                if isinstance(raw.get(k), list):
                    titles = [str(t).strip() for t in raw[k]][:5]
                    break
            else:
                titles = [str(v).strip() for v in raw.values() if isinstance(v, str)][:5]
        else:
            titles = []
        if not titles:
            return jsonify({"ok": False, "error": "Titles generate nahi hue"}), 500
        return jsonify({"ok": True, "titles": titles})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/sync_metadata", methods=["POST"])
def sync_metadata():
    """Jab title change ho to description + tags sync karo (Triple Keyword)."""
    data = request.get_json() or {}
    title    = (data.get("title") or "").strip()
    language = (data.get("language") or "roman-urdu").strip()
    summary  = (data.get("summary") or "").strip()
    transcript = (data.get("transcript") or "").strip()[:800]
    subject  = (data.get("subject") or "").strip()

    if not title:
        return jsonify({"ok": False, "error": "Title missing"}), 400

    lang_rule = {
        "english":    "ALL output in natural English only.",
        "roman-urdu": "ALL output in Roman Urdu/Hindi (Latin a-z letters ONLY). NO Devanagari, NO Arabic script.",
        "hindi":      "ALL output in Devanagari Hindi.",
    }.get(language, "ALL output in Roman Urdu/Hindi (Latin a-z letters only).")

    # Extract primary keyword from title (first meaningful phrase)
    prompt = f"""YouTube SEO expert. A creator just selected this title:
TITLE: "{title}"

VIDEO CONTEXT: {summary}. Subject: {subject}. Transcript: {transcript[:400]}

LANGUAGE: {lang_rule}

Generate ONLY these 3 things matched to this exact title:
1. primary_keyword — the main 3-5 word search phrase from this title
2. description — SEO description (150+ words) where LINE 1 has the EXACT primary_keyword from title, then keyword variations, then engagement question, then CTA "Like + Subscribe", then EXACTLY 3 hashtags (#topic #Shorts #niche)
3. tags — 20-25 relevant tags (no #), comma-separated, 400-480 chars total, primary_keyword FIRST

Return JSON: {{"primary_keyword":"...", "description":"...", "tags":["tag1","tag2",...]}}
"""
    try:
        from core import llm as _llm
        result = _llm.generate(prompt)
        if not isinstance(result, dict):
            return jsonify({"ok": False, "error": "Bad response"}), 500
        tags = result.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        # dedupe + no #
        seen, clean = set(), []
        for t in tags:
            t = t.strip().lstrip("#").lower()
            if t and t not in seen: seen.add(t); clean.append(t)
        return jsonify({
            "ok": True,
            "primary_keyword": result.get("primary_keyword",""),
            "description": result.get("description",""),
            "tags": clean[:25],
            "tags_string": ", ".join(clean[:25]),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/refresh_tags", methods=["POST"])
def refresh_tags():
    """Naye tag suggestions — har baar alag variations use karo."""
    data = request.get_json() or {}
    keyword  = (data.get("keyword") or "").strip()
    language = (data.get("language") or "roman-urdu").strip()
    round_n  = int(data.get("round") or 0)   # 0,1,2... har call pe cycle karo
    if not keyword:
        return jsonify({"ok": False, "error": "Keyword missing"}), 400
    try:
        from core import seo_research as _sr, tag_score as _ts

        # Har round mein alag seed queries use karo
        extra_seeds_en = [
            f"best {keyword}", f"{keyword} for beginners", f"top {keyword}",
            f"{keyword} tutorial", f"how to {keyword}", f"{keyword} tips",
        ]
        extra_seeds_desi = [
            f"{keyword} ke fayde", f"{keyword} kaise kare", f"best {keyword} hindi",
            f"{keyword} short film", f"{keyword} story", f"top {keyword} hindi",
        ]
        seeds = extra_seeds_desi if language in ("roman-urdu","hindi") else extra_seeds_en
        seed = seeds[round_n % len(seeds)]

        # Step 1: Autocomplete se real search data
        base  = _sr.get_keyword_clusters(keyword, language)
        extra = _sr.get_keyword_clusters(seed, language)

        autocomplete_tags = []
        seen = set()
        for t in (base.get("tag_ready",[]) + extra.get("tag_ready",[])):
            tl = t.lower().strip()
            if tl and tl not in seen: seen.add(tl); autocomplete_tags.append(t)

        # Step 2: LLM se proper short YouTube tags (autocomplete data ke saath)
        from core import llm as _llm
        lang_ex = "English" if language == "english" else "Roman Urdu/Hindi (Latin letters only)"
        llm_prompt = (
            f"Generate 15 short YouTube TAGS for a video about: '{keyword}'\n"
            f"Language: {lang_ex}\n"
            f"Real searched keywords (use as inspiration): {', '.join(autocomplete_tags[:8])}\n\n"
            "RULES:\n"
            "- Each tag: 2-4 words only (short, clean phrases)\n"
            "- NO question format (no kaise/kyun/how/why)\n"
            "- NO hashtag symbol\n"
            "- Mix: exact keyword variants + related topics + broad category\n"
            "- Examples of GOOD tags: 'phal ke fayde', 'healthy fruits hindi', 'immunity boost fruits'\n"
            "- Examples of BAD tags: 'kaise phal khaoge', 'phal khane ke kya fayde hain'\n\n"
            "Return ONLY JSON array: [\"tag1\", \"tag2\", ...]"
        )
        try:
            llm_result = _llm.generate(llm_prompt)
            if isinstance(llm_result, list):
                llm_tags = [str(t).strip().lower().lstrip('#') for t in llm_result if str(t).strip()]
            elif isinstance(llm_result, dict):
                for k in ["tags","result","data","items"]:
                    if isinstance(llm_result.get(k), list):
                        llm_tags = [str(t).strip().lower().lstrip('#') for t in llm_result[k]]
                        break
                else:
                    llm_tags = []
            else:
                llm_tags = []
        except Exception:
            llm_tags = []

        # Merge: LLM tags first (cleaner), then autocomplete
        final_seen, all_tags = set(), []
        for t in (llm_tags + autocomplete_tags):
            tl = t.lower().strip()
            words = tl.split()
            if tl and tl not in final_seen and 1 < len(words) <= 5:
                final_seen.add(tl); all_tags.append(t)

        all_tags = all_tags[:25]
        scores = _ts.score_tags_bulk(all_tags, language=language)
        return jsonify({"ok": True, "tags": all_tags, "scores": scores})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/refine", methods=["POST"])
def refine():
    """User ki instruction se specific field fix karo."""
    data = request.get_json() or {}
    instruction = (data.get("instruction") or "").strip()
    current_desc = (data.get("description") or "").strip()
    current_tags = data.get("tags") or []
    current_titles = data.get("titles") or []
    language = (data.get("language") or "roman-urdu").strip()
    primary_kw = (data.get("primary_keyword") or "").strip()

    if not instruction:
        return jsonify({"ok": False, "error": "Instruction missing"}), 400

    lang_rule = "Roman Urdu/Hindi (Latin letters only)" if language in ("roman-urdu","hindi") else "English"

    prompt = f"""You are a YouTube metadata editor. A creator gave ONE specific instruction.

⚠️ STRICT RULE: Do ONLY what the instruction says. Do NOT change anything else.
- If instruction says "add hashtags" → ONLY add hashtags to description. Keep everything else EXACTLY the same — same words, same length, same sentences.
- If instruction says "fix title" → ONLY change titles. Description and tags stay identical.
- NEVER shorten, rewrite, or improve anything that was not mentioned in the instruction.
- NEVER add extra changes "for improvement" — only the exact requested change.

CURRENT METADATA:
- Description: {current_desc}
- Tags: {', '.join(current_tags[:15])}
- Titles: {current_titles[:3]}
- Primary keyword: {primary_kw}
- Language: {lang_rule}

CREATOR'S INSTRUCTION: "{instruction}"

Return JSON with ONLY the field(s) that changed (omit unchanged fields):
{{
  "description": "full description — IDENTICAL to original EXCEPT for the requested change",
  "tags": ["only if tags were asked to change"],
  "titles": ["only if titles were asked to change"],
  "message": "1 line: exactly what was done"
}}
"""
    try:
        from core import llm as _llm
        result = _llm.generate(prompt)
        if not isinstance(result, dict):
            return jsonify({"ok": False, "error": "Bad response"}), 500
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/keyword_opportunity", methods=["POST"])
def keyword_opportunity():
    """TubeBuddy-style keyword opportunity score."""
    data = request.get_json() or {}
    keyword = (data.get("keyword") or "").strip()
    language = (data.get("language") or "roman-urdu").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Keyword missing"}), 400
    try:
        from core.tag_score import keyword_opportunity_score
        result = keyword_opportunity_score(keyword, language)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


def _open_browser(url: str):
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5055"))
    is_cloud = os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT")
    host = "0.0.0.0" if is_cloud else "127.0.0.1"

    print("=" * 60)
    print("  MeloToons Title Generator")
    if is_cloud:
        print(f"  Running on cloud — port {port}")
    else:
        url = f"http://127.0.0.1:{port}"
        print(f"  Open:  {url}")
        threading.Timer(1.2, _open_browser, args=[url]).start()
    print("=" * 60)
    app.run(host=host, port=port, debug=False)
