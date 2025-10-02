# ====================================================================
# File: python_api/summarizer.py (improved)
# - safer when GEMINI_API_KEY missing (no exception raised)
# - better debug logging (chunks, partial counts, errors)
# - clearer ThreadPoolExecutor variable name
# ====================================================================

import google.generativeai as genai
from dotenv import load_dotenv
import os
import traceback
import concurrent.futures
import re
import logging
from typing import List, Dict, Any, Optional

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Initialize API ---
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_MODEL = "gemini-2.5-flash"

if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
    except Exception:
        logger.exception("Error configuring genai with provided API key.")
else:
    logger.warning("GEMINI_API_KEY not found in .env file. Summarizer will work in a no-op/fallback mode.")


# ------------------------
# Low-level Gemini call
# ------------------------
def _call_gemini(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Call Gemini API and return text result or empty string on failure."""
    if not API_KEY:
        # No API key — return empty string (caller will treat as a failed partial)
        logger.debug("_call_gemini: no API key configured; skipping model call.")
        return ""

    try:
        m = genai.GenerativeModel(model)
        resp = m.generate_content(prompt)
        text = resp.text if resp and getattr(resp, "text", None) else ""
        return text or ""
    except Exception:
        logger.exception("_call_gemini failed")
        return ""


# ------------------------
# Chunk summarizer (parallel)
# ------------------------
def _summarize_chunk(args):
    # args is a tuple (text_chunk, model)
    text_chunk, model = args
    prompt = f"""
You are an expert academic tutor. Summarize the following chunk into concise,
exam-focused study points in Markdown. Use short bullet points and keep it tight.

[Chunk]
{text_chunk}
"""
    return _call_gemini(prompt, model=model)


# ------------------------
# Fast title extraction from merged partials
# ------------------------
def _extract_title_from_partials(partials_merged: str, model: str = DEFAULT_MODEL) -> str:
    if not partials_merged:
        return ""
    prompt = f"""
You are a helpful assistant. Read the below merged partial study notes and supply a
concise title (3-8 words) that best captures the main topic. Output only the title
on a single line (no markdown, no bullets, no extra text).

[Merged partial summaries]
{partials_merged}

Title:
"""
    raw = _call_gemini(prompt, model=model)
    if not raw:
        return ""

    line = raw.splitlines()[0].strip() if raw.splitlines() else raw.strip()
    line = re.sub(r'^[\"\']+|[\"\']+$', '', line)  # strip quotes
    line = re.sub(r'^[\-\–\—\d\.\)\s]+', '', line)  # strip leading bullets/nums
    line = re.sub(r'\s+', ' ', line)
    words = line.split()
    if len(words) > 8:
        line = ' '.join(words[:8])
    return line.strip()


# ------------------------
# Final refinement + merge (uses partials as input)
# ------------------------
def _refine_and_merge_partials(partials: List[str], model: str = DEFAULT_MODEL) -> str:
    merged_text = "\n\n".join(partials)
    prompt = f"""
You are an expert academic tutor. Merge the following partial summaries into
one clean, non-redundant, exam-focused study note in Markdown.

Requirements:
- Remove overlaps/redundancies.
- Organize into clear sections and headings as needed.
- Keep it concise but exam-ready.

[Partial Summaries]
{merged_text}
"""
    return _call_gemini(prompt, model=model) or merged_text


# ------------------------
# Public function
# ------------------------
def generate_study_notes_with_api(
    text: str,
    chunk_size: int = 2000,
    parallel: bool = True,
    quick_title_only: bool = False,
    model: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    """
    Returns dict: { 'notes': <markdown str> , 'title': <short str>, 'partials': [ ... ] }

    This function will NOT raise if no API key is present; instead it returns
    an empty/fallback result so callers can continue (and update DB).
    """
    try:
        if not text or not isinstance(text, str):
            return {"notes": "", "title": "", "partials": []}

        # split into chunks by simple char windows
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        logger.debug("generate_study_notes_with_api: text length=%d chunk_size=%d chunks=%d", len(text), chunk_size, len(chunks))

        # Summarize chunks (parallel or sequential)
        partials: List[str] = []
        if parallel and len(chunks) > 1:
            try:
                max_workers = min(8, len(chunks))
                args_iter = ((c, model) for c in chunks)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    results = list(executor.map(_summarize_chunk, args_iter))
                    partials.extend(results)
            except Exception:
                logger.exception("Parallel summarization failed, falling back to sequential")
                for c in chunks:
                    partials.append(_summarize_chunk((c, model)))
        else:
            for c in chunks:
                partials.append(_summarize_chunk((c, model)))

        logger.debug("generate_study_notes_with_api: got %d partials (including empty/error ones)", len(partials))

        # Filter out empty or error partials
        filtered_partials = [p for p in partials if p and isinstance(p, str) and not p.strip() == ""]
        logger.debug("generate_study_notes_with_api: filtered partials count=%d", len(filtered_partials))

        # Build merged partials string
        merged_partials = "\n\n".join(filtered_partials).strip()

        # Fast single call to extract title from merged partials
        title = ""
        try:
            if merged_partials:
                title = _extract_title_from_partials(merged_partials, model=model)
                logger.debug("generate_study_notes_with_api: extracted title='%s'", title)
        except Exception:
            logger.exception("Title extraction failed")
            title = ""

        if quick_title_only:
            return {"notes": "", "title": title, "partials": filtered_partials}

        # If no filtered partials (all failed) we fall back to merged raw partials or empty string
        if not filtered_partials:
            fallback_text = "\n\n".join([p for p in partials if p and isinstance(p, str)]) or ""
            return {"notes": fallback_text, "title": title or "", "partials": partials}

        # Otherwise, produce final refined notes (single additional call)
        final_notes = ""
        try:
            final_notes = _refine_and_merge_partials(filtered_partials, model=model)
        except Exception:
            logger.exception("Refinement of partials failed, using merged partials as fallback")
            final_notes = merged_partials

        return {"notes": final_notes or merged_partials, "title": title or "", "partials": filtered_partials}

    except Exception:
        logger.exception("generate_study_notes_with_api: unexpected error")
        # Ensure we never raise to the caller — return a safe empty structure
        return {"notes": "", "title": "", "partials": []}
