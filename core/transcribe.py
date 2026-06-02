"""Video se asli script + language nikaalna.

Priority:
  1. Groq Whisper API (free, fast ~3-5 sec) — agar GROQ_API_KEY ho
  2. Local faster-whisper (CPU, slow ~60-90 sec) — fallback

Language auto-detect hoti hai. None return karta hai agar speech nahi.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

# Whisper lang code -> tool ka language mode
_LANG_MAP = {
    # ISO codes (local Whisper)
    "en": "english",
    "hi": "roman-urdu",
    "ur": "roman-urdu",
    "pa": "roman-urdu",
    # Full names (Groq Whisper returns full names)
    "english": "english",
    "hindi": "roman-urdu",
    "urdu": "roman-urdu",
    "punjabi": "roman-urdu",
    "hinglish": "roman-urdu",
}


def suggested_mode(lang_code: str) -> str:
    return _LANG_MAP.get((lang_code or "").lower(), "roman-urdu")


def _extract_audio(video_path: str, log=print) -> Optional[Path]:
    """ffmpeg se 16k mono wav nikalo."""
    out = Path(tempfile.gettempdir()) / f"ytt_{uuid.uuid4().hex}.wav"
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1",
           "-ar", "16000", "-f", "wav", "-t", "120", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception as e:
        log(f"[whisper] ffmpeg fail: {e}")
        return None
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
        log("[whisper] koi audio track nahi")
        return None
    return out


# ── Groq Whisper (fast, free) ────────────────────────────────────────────

def _groq_transcribe(video_path: str, log=print) -> Optional[dict]:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    audio = _extract_audio(video_path, log=log)
    if audio is None:
        return None
    try:
        log("[whisper] Groq Whisper se transcribing (fast) ...")
        from groq import Groq
        client = Groq(api_key=api_key)
        with open(audio, "rb") as f:
            resp = client.audio.transcriptions.create(
                file=(audio.name, f, "audio/wav"),
                model="whisper-large-v3-turbo",
                response_format="verbose_json",
                temperature=0.0,
            )
        text = (resp.text or "").strip()
        lang = (getattr(resp, "language", None) or "").lower()
        if len(text) < 8:
            log("[whisper] speech bohot kam")
            return None
        log(f"[whisper] Groq done: lang={lang}, {len(text)} chars")
        return {"language": lang, "language_prob": 0.99, "text": text,
                "suggested_mode": suggested_mode(lang)}
    except Exception as e:
        log(f"[whisper] Groq fail: {str(e)[:100]}")
        return None
    finally:
        try: audio.unlink(missing_ok=True)
        except Exception: pass


# ── Local faster-whisper (fallback) ─────────────────────────────────────

_local_model = None
_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "tiny")


def _local_transcribe(video_path: str, log=print) -> Optional[dict]:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        log("[whisper] faster-whisper nahi — skip")
        return None
    audio = _extract_audio(video_path, log=log)
    if audio is None:
        return None
    try:
        global _local_model
        log(f"[whisper] local ({_MODEL_SIZE}) transcribing ...")
        if _local_model is None:
            from faster_whisper import WhisperModel
            _local_model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
        segments, info = _local_model.transcribe(str(audio), beam_size=1,
                                                  vad_filter=True, best_of=1)
        text = " ".join(s.text.strip() for s in segments).strip()
        if len(text) < 8:
            return None
        lang = (info.language or "").lower()
        log(f"[whisper] local done: lang={lang}, {len(text)} chars")
        return {"language": lang, "language_prob": round(float(info.language_probability), 2),
                "text": text, "suggested_mode": suggested_mode(lang)}
    except Exception as e:
        log(f"[whisper] local fail: {str(e)[:100]}")
        return None
    finally:
        try: audio.unlink(missing_ok=True)
        except Exception: pass


# ── Public API ────────────────────────────────────────────────────────────

def transcribe(video_path: str, log=print) -> Optional[dict]:
    """Returns {language, language_prob, text, suggested_mode} ya None.
    Groq (fast) -> local (fallback).
    """
    # Groq se try karo (fast)
    r = _groq_transcribe(video_path, log=log)
    if r:
        return r
    # Local fallback
    return _local_transcribe(video_path, log=log)

