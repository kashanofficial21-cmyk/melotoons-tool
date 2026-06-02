"""Video se key frames extract karo — LLM ko visual context dene ke liye.

ffmpeg se 4-6 frames nikalta hai (evenly spaced), base64 encode karta hai.
Yeh frames prompt mein text description ke roop mein Groq ko bheje jaate hain.
"""

from __future__ import annotations
import base64
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional


def extract_frames(video_path: str, n: int = 5, log=print) -> list[str]:
    """n evenly-spaced frames nikalo, base64 PNG strings return karo."""
    try:
        # Video duration nikalo
        dur_r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10
        )
        duration = float(dur_r.stdout.strip() or "30")

        # Evenly spaced timestamps
        step = duration / (n + 1)
        timestamps = [round(step * (i + 1), 2) for i in range(n)]

        frames = []
        tmp_dir = Path(tempfile.gettempdir()) / f"ytt_frames_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(exist_ok=True)

        for i, ts in enumerate(timestamps):
            out = tmp_dir / f"f{i:02d}.jpg"
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
                 "-frames:v", "1", "-q:v", "5", "-vf", "scale=320:-1", str(out)],
                capture_output=True, timeout=10
            )
            if r.returncode == 0 and out.exists() and out.stat().st_size > 500:
                with open(out, "rb") as f:
                    frames.append(base64.b64encode(f.read()).decode("utf-8"))
            try:
                out.unlink()
            except Exception:
                pass

        try:
            tmp_dir.rmdir()
        except Exception:
            pass

        log(f"[frames] {len(frames)}/{n} frames extracted")
        return frames

    except Exception as e:
        log(f"[frames] skip: {str(e)[:80]}")
        return []


def frames_to_description(frames: list[str], log=print) -> str:
    """Frames ko Groq vision se describe karwao — YouTube metadata ke liye optimized."""
    if not frames:
        return ""
    try:
        import os, json
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            return ""

        client = Groq(api_key=api_key)
        content = [{"type": "text", "text":
            "You are analyzing frames from a YouTube Shorts video to help write metadata.\n\n"
            "Look at ALL frames carefully and answer:\n"
            "1. MAIN CHARACTER: Who/what is the main subject? (cute cat, animated boy, cartoon animal, etc.) — describe appearance, color, expression, emotion\n"
            "2. STORY/ACTION: What is happening? What is the character doing? What is the emotional arc?\n"
            "3. SETTING: Where does it take place? (kitchen, street, school, forest, etc.)\n"
            "4. THEME: What is the main message/theme? (kindness, friendship, health, moral lesson, funny moment, etc.)\n"
            "5. MOOD: What emotion does this video convey? (happy, sad, suspenseful, heartwarming, funny)\n"
            "6. KEYWORDS: List 3-5 specific keywords that describe this video's topic\n\n"
            "Be SPECIFIC and CONCRETE — no vague descriptions. This is used for YouTube SEO metadata.\n"
            "Format your response as plain text with these 6 points clearly answered."}]

        for b64 in frames[:5]:  # max 5 frames for better coverage
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })

        resp = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": content}],
            max_tokens=500,
            temperature=0.2,
        )
        desc = resp.choices[0].message.content or ""
        log(f"[frames] visual analysis: {len(desc)} chars")
        return desc.strip()

    except Exception as e:
        log(f"[frames] vision skip: {str(e)[:80]}")
        return ""


def extract_visual_keyword(visual_desc: str, language: str = "roman-urdu") -> str:
    """Visual description se primary keyword nikalo (no-audio videos ke liye)."""
    if not visual_desc:
        return ""
    try:
        import os
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            return ""
        client = Groq(api_key=api_key)
        lang = "Roman Urdu/Hindi" if language in ("roman-urdu", "hindi") else "English"
        prompt = (
            f"From this video description, extract the SINGLE BEST YouTube search keyword (3-5 words max) in {lang}:\n\n"
            f"{visual_desc[:400]}\n\n"
            "Return ONLY the keyword phrase, nothing else. Example: 'cute cat rescue story' or 'billi ki madad'"
        )
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0.1,
        )
        kw = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
        return kw
    except Exception:
        return ""
