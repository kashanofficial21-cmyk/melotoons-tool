"""Multi-provider LLM backend — Groq (primary) → Cerebras → Gemini → fallback.

Sab free tier. Whisper transcript se metadata generate karta hai.
Priority: Groq (fast) → Cerebras → Gemini (agar key ho).
"""

from __future__ import annotations
import json, os, re, time
from typing import Optional

# ── helpers ────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    raw = raw.strip().strip("`").strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e != -1:
        raw = raw[s:e+1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = re.sub(r",(\s*[}\]])", r"\1", raw)
        fixed = fixed.replace("“",'"').replace("”",'"').replace("’","'")
        return json.loads(fixed)


def _is_transient(msg: str) -> bool:
    return any(x in msg for x in ("429","503","rate","quota","overload","unavailable","timeout","exhausted","high demand"))


# ── GROQ ───────────────────────────────────────────────────────────────────

_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
]

def _groq_generate(prompt: str, log=print) -> str:
    api_key = os.environ.get("GROQ_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing")
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("groq package missing — pip install groq")

    client = Groq(api_key=api_key)
    for model in _GROQ_MODELS:
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role":"user","content": prompt}],
                    temperature=0.85,
                    max_tokens=2048,
                    response_format={"type":"json_object"},
                )
                log(f"[groq] done via {model}")
                return resp.choices[0].message.content or ""
            except Exception as e:
                msg = str(e).lower()
                if "decommissioned" in msg or "not found" in msg or "does not exist" in msg:
                    log(f"[groq] {model} unavailable, next model")
                    break
                if _is_transient(msg):
                    log(f"[groq] {model} rate limited, retry {attempt+1}")
                    time.sleep(1 + attempt)
                    continue
                raise
    raise RuntimeError("Groq rate limited — 1 minute ruk kar dobara try karein.")


# ── CEREBRAS ───────────────────────────────────────────────────────────────

def _cerebras_generate(prompt: str, log=print) -> str:
    api_key = os.environ.get("CEREBRAS_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY missing")
    try:
        from cerebras.cloud.sdk import Cerebras
    except ImportError:
        raise RuntimeError("cerebras-cloud-sdk missing — pip install cerebras-cloud-sdk")

    client = Cerebras(api_key=api_key)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama3.1-70b",
                messages=[{"role":"user","content": prompt}],
                temperature=0.85,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            msg = str(e).lower()
            if _is_transient(msg):
                log(f"[cerebras] transient ({str(e)[:80]}), retry {attempt+1}")
                time.sleep(2 + attempt*2)
                continue
            raise
    raise RuntimeError("Cerebras 3 retries failed")


# ── GEMINI (text-only, no video) ───────────────────────────────────────────

def _gemini_text_generate(prompt: str, log=print) -> str:
    api_key = os.environ.get("GEMINI_API_KEY","").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai missing")

    client = genai.Client(api_key=api_key)
    models = ["gemini-2.5-flash","gemini-flash-latest","gemini-2.0-flash"]
    for model in models:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.85,
                        max_output_tokens=2048,
                    ),
                )
                t = getattr(resp,"text",None) or ""
                if not t:
                    for cand in getattr(resp,"candidates",[]) or []:
                        for part in getattr(getattr(cand,"content",None),"parts",[]) or []:
                            pt = getattr(part,"text",None)
                            if pt: t += pt
                return t.strip()
            except Exception as e:
                msg = str(e).lower()
                if _is_transient(msg) or "location" in msg:
                    log(f"[gemini-text] {model} busy, retry {attempt+1}")
                    time.sleep(2)
                    continue
                raise
    raise RuntimeError("Gemini text 3 retries failed")


# ── PUBLIC: generate with auto-fallback ────────────────────────────────────

PROVIDERS = [
    ("Groq",     _groq_generate),
    ("Cerebras", _cerebras_generate),
    ("Gemini",   _gemini_text_generate),
]


def generate(prompt: str, log=print) -> dict:
    """Try providers in order. Returns parsed JSON dict."""
    last_err = None
    for name, fn in PROVIDERS:
        try:
            raw = fn(prompt, log=log)
            data = _parse_json(raw)
            log(f"[llm] done via {name}")
            return data
        except RuntimeError as e:
            msg = str(e)
            if "missing" in msg.lower():
                log(f"[llm] {name} skip: {msg}")
                continue          # key/package nahi — agla try karo
            last_err = e
            log(f"[llm] {name} fail: {msg[:100]}, trying next")
            continue
        except Exception as e:
            last_err = e
            log(f"[llm] {name} error: {str(e)[:100]}, trying next")
            continue
    raise RuntimeError(
        "⏳ Saare AI providers rate-limited hain. "
        "1-2 minute ruk kar dobara try karein — Groq free tier: 30 req/min. "
        f"({str(last_err)[:80]})"
    )


def available_providers() -> list[str]:
    available = []
    if os.environ.get("GROQ_API_KEY","").strip():
        available.append("Groq")
    if os.environ.get("CEREBRAS_API_KEY","").strip():
        available.append("Cerebras")
    if os.environ.get("GEMINI_API_KEY","").strip():
        available.append("Gemini")
    return available
