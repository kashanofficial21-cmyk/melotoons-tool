"""MeloToons Title Generator — video upload karo, viral title/description/tags lo.

Chalao:  python app.py   (phir browser khud khulega:  http://127.0.0.1:5055)
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
import uuid
import webbrowser
from pathlib import Path

# Windows console encoding fix — prevents crash on Unicode/emoji in print()
import io as _io
try:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

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
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # No caching
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True


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
        print(f"[generate] video={file.filename} lang={lang} skip_tr={skip_tr} hint='{hint[:50]}'", flush=True)
        result = analyzer.analyze_video(str(tmp), extra_hint=hint, lang_pref=lang,
                                        use_transcript=not skip_tr)
        result["analyzed_file"] = file.filename
        _has_t = bool(result.get("transcript", "").strip())
        _has_v = result.get("has_visual", False)
        result["context_quality"] = (
            "transcript+visual" if _has_t and _has_v else
            "transcript"        if _has_t else
            "visual_only"       if _has_v else
            "title_only"
        )
        print(f"[generate] done: lang={result.get('detected_language')} kw={result.get('primary_keyword','?')[:30]}", flush=True)
        return jsonify({"ok": True, "result": result})
    except analyzer.AnalyzerError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        try:
            print(tb, flush=True)
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"Unexpected: {e}", "traceback": tb[-800:]}), 500
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/analyze_url", methods=["POST"])
def analyze_url():
    """YouTube URL se FAST analyze — sirf transcript + thumbnails (full download nahi)."""
    data = request.get_json() or {}
    url   = (data.get("url") or "").strip()
    lang  = (data.get("lang") or "auto").strip()
    hint  = (data.get("hint") or "").strip()

    if not url or ("youtube" not in url and "youtu.be" not in url):
        return jsonify({"ok": False, "error": "Valid YouTube URL daalo"}), 400

    import subprocess, uuid, tempfile, json as _json, concurrent.futures
    tmp_dir = Path(tempfile.gettempdir()) / f"yt_{uuid.uuid4().hex}"
    tmp_dir.mkdir(exist_ok=True)

    try:
        # Step 1: Download video + info only (no subtitles — causes 429)
        meta_r = subprocess.run([
            "yt-dlp",
            "-f", "worst[ext=mp4]/best[height<=360][ext=mp4]/best",
            "--write-info-json", "--no-playlist",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--extractor-retries", "3",
            "-o", str(tmp_dir / "video.%(ext)s"), url
        ], capture_output=True, timeout=180, text=True)

        if meta_r.returncode != 0:
            # Check if it's a 429 rate limit
            stderr = meta_r.stderr or ""
            if "429" in stderr:
                return jsonify({"ok": False, "error": "YouTube rate limit — 5-10 minute baad dobara try karo"}), 429
            if not list(tmp_dir.iterdir()):  # No files at all
                return jsonify({"ok": False, "error": f"Video download nahi hua. Wajah: {stderr[-150:]}"}), 500

        # Read metadata
        info = {}
        for f in tmp_dir.glob("*.info.json"):
            with open(f, encoding='utf-8', errors='replace') as fp:
                info = _json.load(fp)
            break

        existing_title = info.get("title", "")
        existing_desc  = info.get("description", "")[:500]
        existing_tags  = info.get("tags", [])[:10]
        duration       = info.get("duration", 0)
        thumb_url      = info.get("thumbnail", "")

        # Read transcript — prefer Hindi/Urdu captions first
        transcript_text = ""
        detected_lang   = "roman-urdu"  # MeloToons default desi channel

        import re as _re
        all_vtt = sorted(tmp_dir.glob("*.vtt"), key=lambda f: (0 if any(x in f.name for x in ["hi","ur","pa"]) else 1))
        for f in all_vtt:
            lines = []
            for line in open(f, encoding='utf-8', errors='replace'):
                line = line.strip()
                if line and not line.startswith("WEBVTT") and "-->" not in line and not line.startswith("align:"):
                    clean = _re.sub(r'<[^>]+>', '', line)
                    if clean and clean not in lines[-1:]:
                        lines.append(clean)
            if lines:
                transcript_text = " ".join(lines[:200])
                if "en" in f.name and "hi" not in f.name and "ur" not in f.name:
                    detected_lang = "english"
                else:
                    detected_lang = "roman-urdu"
                break

        # Step 2: Download thumbnail for visual analysis
        visual_desc = ""
        if thumb_url:
            try:
                import urllib.request, base64
                thumb_path = tmp_dir / "thumb.jpg"
                urllib.request.urlretrieve(thumb_url, str(thumb_path))
                with open(thumb_path, 'rb') as tf:
                    b64 = base64.b64encode(tf.read()).decode()
                from core.frames import frames_to_description
                visual_desc = frames_to_description([b64], log=lambda x: None)
            except Exception:
                pass

        # Step 3: Use downloaded video for Whisper + frames (full analysis)
        video_files = list(tmp_dir.glob("video.mp4")) + list(tmp_dir.glob("video.webm")) + list(tmp_dir.glob("video.*"))
        video_files = [f for f in video_files if f.suffix in ('.mp4','.webm','.mkv','.m4v')]

        if video_files:
            vf = video_files[0]
            # Whisper transcription — ALWAYS run for accurate language detection
            try:
                from core.transcribe import _groq_transcribe, suggested_mode
                tr = _groq_transcribe(str(vf))
                if tr and tr.get("text"):
                    transcript_text = tr["text"]  # Whisper overrides captions
                    # Map Whisper language to output mode
                    detected_lang = suggested_mode(tr.get("language", ""))
                    print(f"[url] Whisper lang={tr.get('language')} → {detected_lang}", flush=True)
            except Exception as e:
                print(f"[url] Whisper failed: {e}", flush=True)
            # Visual frames analysis
            if not visual_desc:
                try:
                    from core.frames import extract_frames, frames_to_description
                    frms = extract_frames(str(vf), n=5)
                    if frms:
                        visual_desc = frames_to_description(frms)
                except Exception:
                    pass

        # Step 4: Effective language
        # auto = use Whisper detection | manual = force user selection
        if lang == "auto":
            eff_lang = detected_lang
        else:
            eff_lang = lang
        print(f"[url] eff_lang={eff_lang} (user_pref={lang}, detected={detected_lang})", flush=True)

        from core import llm as _llm
        from core.analyzer import _SYSTEM_PROMPT, _normalize, _auto_fix, _seo_score
        import uuid as _uuid

        # Context quality check — kuch na ho to fail loudly
        has_real_content = bool(transcript_text.strip()) or bool(visual_desc.strip())
        if not has_real_content and not existing_title.strip():
            return jsonify({"ok": False, "error":
                "Video se kuch bhi analyze nahi ho saka. "
                "Video private/deleted ho sakti hai, ya download fail hua. "
                "Video directly upload karo (neeche wala section)."
            }), 400

        req_id = _uuid.uuid4().hex[:12]  # Groq cache break

        # VIDEO CONTENT PEHLE — LLM actual video ko prioritize kare, template se nahi
        video_context = f"REQUEST_ID: {req_id}\n\n"
        video_context += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        video_context += "⭐ IS VIDEO KA ACTUAL CONTENT (PEHLE PADHO — YAHI PRIMARY SOURCE HAI)\n"
        video_context += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        if existing_title:
            video_context += f"YOUTUBE VIDEO TITLE: {existing_title}\n"
        if existing_tags:
            video_context += f"EXISTING TAGS (improve karo): {', '.join(existing_tags[:8])}\n"
        if transcript_text:
            video_context += (
                f"\nAUDIO TRANSCRIPT (Whisper) — YEH ASLI SCRIPT HAI:\n"
                f'"""\n{transcript_text[:2000]}\n"""\n'
                "↑ Transcript se characters, story, topic exactly samjho. Generic mat banao.\n"
            )
        else:
            video_context += "\n⚠️ Transcript nahi mila — visual + title se analyze karo.\n"
        if visual_desc:
            video_context += (
                f"\nVIDEO VISUAL DESCRIPTION:\n{visual_desc[:400]}\n"
                "↑ Characters, setting, actions exactly dekho.\n"
            )
        if hint:
            video_context += f"\nUSER HINT: {hint}\n"
        if not transcript_text and not visual_desc:
            video_context += f"\n⚠️ Sirf title available hai: '{existing_title}' — is pe best possible SEO banao.\n"

        prompt = video_context + "\n" + _SYSTEM_PROMPT.replace("{mode}", eff_lang) + f"\n\nLANGUAGE_MODE = {eff_lang}\n"

        data_out = _llm.generate(prompt)
        result = _normalize(data_out)
        result["transcript"] = transcript_text[:300]
        result["whisper_language"] = detected_lang
        result["analyzed_title"] = existing_title  # UI mein confirm karne ke liye
        result["analyzed_url"] = url
        result["context_quality"] = (
            "transcript+visual" if transcript_text and visual_desc else
            "transcript" if transcript_text else
            "visual" if visual_desc else
            "title_only"
        )
        result = _auto_fix(result)

        # SEO research
        try:
            from core import seo_research as _sr, tag_score as _ts
            kw = result.get("primary_keyword","")
            if kw:
                seo = _sr.full_research(kw, result.get("content_summary",""), eff_lang)
                new_tags = [t for t in seo.get("keyword_tags",[]) if t not in result.get("tags",[])]
                merged = result.get("tags",[]) + new_tags
                packed, chars = [], 0
                for t in merged:
                    add = (", " if packed else "") + t
                    if chars + len(add) > 490: break
                    packed.append(t); chars += len(add)
                result["tags"] = packed
                result["tags_string"] = ", ".join(packed)
                result["tags_chars"] = len(result["tags_string"])
                result["search_keywords"] = seo.get("keyword_suggestions",[])
                result["trends"] = seo.get("trends",{})
                result["competitors"] = seo.get("competitors",{})
                result["posting_strategy"] = seo.get("posting_strategy",{})
                result["tag_scores"] = _ts.score_tags_bulk(result["tags"][:15], language=eff_lang)
        except Exception:
            pass

        result["seo"] = _seo_score(result)
        return jsonify({"ok": True, "result": result})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
    finally:
        import shutil
        try: shutil.rmtree(tmp_dir, ignore_errors=True)
        except: pass


@app.route("/video_ideas", methods=["POST"])
def video_ideas():
    """Trending niche pe based video ideas generate karo."""
    data = request.get_json() or {}
    language = (data.get("language") or "roman-urdu").strip()
    niche = (data.get("niche") or "cute animated moral story hindi urdu").strip()

    try:
        # Step 1: Trending topics from YouTube autocomplete
        from core.seo_research import _yt_autocomplete, get_competitor_data
        seeds = {
            "roman-urdu": ["cute billi story", "moral kahani hindi", "emotional animated", "pyaari kahani"],
            "english": ["cute cat animation", "moral story animated", "emotional story kids"],
        }.get(language, ["cute billi story", "moral kahani hindi"])

        trending = []
        seen = set()
        for seed in seeds[:3]:
            for s in _yt_autocomplete(seed, hl="hi" if language != "english" else "en"):
                if s.lower() not in seen and len(s) > 5:
                    seen.add(s.lower()); trending.append(s)

        # Step 2: Competitor top videos
        comp = get_competitor_data("cute animated moral story hindi", max_results=5)
        top_titles = [v["title"][:60] for v in comp.get("top_videos", [])[:5]]

        # Step 3: LLM generates 10 video ideas
        lang_rule = "Roman Urdu/Hindi (Latin letters only)" if language != "english" else "English"
        prompt = f"""You are a viral YouTube Shorts idea generator for MeloToons channel.
Channel niche: AI 3D Pixar-style cute animated emotional/moral stories (desi Pakistani/Indian audience).
Language for ideas: {lang_rule}

TRENDING searches in this niche right now:
{', '.join(trending[:12])}

TOP performing competitor videos:
{chr(10).join(top_titles)}

Generate 8 UNIQUE video ideas that:
1. Match MeloToons niche (cute animals/children, moral/emotional stories, 3D animation)
2. Are NOT already done by competitors (fresh angles)
3. Have high viral potential for desi audience
4. Each idea has a specific character + situation + emotional hook

Return JSON array of 8 objects:
[{{
  "title": "Ready-to-use viral title (matched language, 40-60 chars, 1 emoji)",
  "concept": "2-line concept: character + what happens + emotional hook",
  "hook": "Pehle 3 second ka opening line",
  "viral_angle": "why this will go viral (emotion/relatability/surprise)",
  "difficulty": "Easy/Medium/Hard to make"
}}]"""

        from core import llm as _llm
        result = _llm.generate(prompt)
        ideas = result if isinstance(result, list) else result.get("ideas", result.get("data", []))
        return jsonify({"ok": True, "ideas": ideas[:8], "trending": trending[:10]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


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


@app.route("/keyword_deep", methods=["POST"])
def keyword_deep():
    data = request.get_json() or {}
    keyword = (data.get("keyword") or "").strip()
    language = (data.get("language") or "roman-urdu").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Keyword missing"}), 400
    try:
        from core.vidiq_features import keyword_score_detailed
        return jsonify({"ok": True, "result": keyword_score_detailed(keyword, language)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/trending_videos", methods=["POST"])
def trending_videos():
    data = request.get_json() or {}
    keyword = (data.get("keyword") or "").strip()
    if not keyword: return jsonify({"ok": False, "error": "Keyword missing"}), 400
    try:
        from core.vidiq_features import get_trending_videos
        return jsonify({"ok": True, "videos": get_trending_videos(keyword)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/best_time", methods=["POST"])
def best_time():
    data = request.get_json() or {}
    language = (data.get("language") or "roman-urdu").strip()
    from core.vidiq_features import best_time_to_publish
    return jsonify({"ok": True, "result": best_time_to_publish(language)})


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
