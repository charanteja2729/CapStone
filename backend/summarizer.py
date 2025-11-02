import os
import re
import json
import logging
import traceback
import concurrent.futures
from typing import List, Dict, Any
from dotenv import load_dotenv
import google.generativeai as genai

# =========================
# Setup Logging
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# Initialize Gemini API
# =========================
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_MODEL = "gemini-2.5-flash"

if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        logger.info("Gemini API configured successfully.")
    except Exception:
        logger.exception("Error configuring genai with provided API key.")
else:
    logger.warning("GEMINI_API_KEY not found. Summarizer will work in fallback mode.")


# =========================
# Low-Level Gemini Call
# =========================
def _call_gemini(prompt: str, model: str = DEFAULT_MODEL, is_json: bool = False) -> str:
    """Call Gemini API and return text result or empty string on failure."""
    if not API_KEY:
        logger.debug("_call_gemini: no API key configured; skipping model call.")
        return ""

    try:
        model_instance = genai.GenerativeModel(model)
        generation_config = {"response_mime_type": "application/json"} if is_json else {}
        response = model_instance.generate_content(prompt, generation_config=generation_config)
        text = response.text if response and getattr(response, "text", None) else ""
        return text or ""
    except Exception:
        logger.exception("_call_gemini failed")
        return ""


# =========================
# Extract Keywords (for Cache Matching)
# =========================
def get_cache_keywords(text: str, model: str = DEFAULT_MODEL) -> List[str]:
    """
    Extracts 5 most important keywords from text for caching.
    Returns a sorted lowercase list of keywords.
    """
    if not text:
        return []

    short_text = (text[:1000] + '...' + text[-1000:]) if len(text) > 2000 else text

    prompt = f"""
You are a text analysis engine. Extract the 5 most important, specific, and defining
keywords from the following text.

Return ONLY a JSON list of lowercase strings.

Example:
["python", "data structures", "dictionaries", "hash maps", "time complexity"]

[Text]
{short_text}

[JSON List]
"""

    try:
        response_str = _call_gemini(prompt, model="gemini-2.5-flash", is_json=True)
        if not response_str:
            return []

        # Extract JSON from Markdown if needed
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_str, re.DOTALL | re.IGNORECASE)
        json_str = json_match.group(1) if json_match else response_str.strip()

        keywords = json.loads(json_str)
        if isinstance(keywords, list):
            return sorted([str(k).lower() for k in keywords if k])
        return []
    except Exception:
        logger.exception("Failed to get cache keywords")
        return []


# =========================
# Chunk Summarizer
# =========================
def _summarize_chunk(args):
    """Summarize one chunk of text."""
    text_chunk, model = args
    prompt = f"""
You are an expert academic tutor. Summarize the following chunk into concise,
exam-focused study points in Markdown. Use short bullet points and keep it tight.

[Chunk]
{text_chunk}
"""
    return _call_gemini(prompt, model=model)


# =========================
# Merge and Refine Summaries
# =========================
def _refine_and_merge_partials(partials: List[str], model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """
    Merges multiple chunk summaries and extracts structured metadata:
    topic, sub_topic, title, and keywords.
    """
    if not partials:
        return {"notes": "", "topic": "", "sub_topic": "", "title": "", "keywords": []}

    merged_text = "\n\n".join(partials)

    prompt = f"""
You are an expert academic tutor. Analyze the following partial summaries and
generate a clean, non-redundant, exam-focused study note in Markdown.

After the notes, provide a structured JSON block with:
- topic: The broad, high-level subject (e.g., "Dynamic Programming").
- sub_topic: The specific concept (e.g., "Tabulation").
- title: A concise title (3-8 words).
- keywords: A list of 5-7 specific, lowercase keywords for cache indexing.

[Partial Summaries]
{merged_text}

[Study Notes]
(Your merged Markdown notes go here, starting with a # Title)

[JSON]
```json
{{
  "topic": "Main academic subject",
  "sub_topic": "Specific concept within the topic",
  "title": "A concise title for this specific summary (3-8 words)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
}}
"""
    raw_response = _call_gemini(prompt, model=model)
    if not raw_response:
        return {
            "notes": merged_text,
            "topic": "",
            "sub_topic": "",
            "title": "Summary",
            "keywords": []
        }

    notes, topic, sub_topic, title, keywords = raw_response, "", "", "", []

    try:
        json_match = re.search(r'json\s*(\{.*?\})\s*', raw_response, re.DOTALL | re.IGNORECASE)
        if json_match:
            json_str = json_match.group(1)
            notes = raw_response[:json_match.start()].strip()
            data = json.loads(json_str)

            topic = data.get("topic", "").strip()
            sub_topic = data.get("sub_topic", "").strip()
            title = data.get("title", "").strip()

            keywords_list = data.get("keywords", [])
            if isinstance(keywords_list, list):
                keywords = sorted([str(k).lower() for k in keywords_list if k])
        else:
            title_match = re.search(r'^#\s*(.*)', notes, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()

    except Exception:
        logger.exception("Failed to parse JSON from Gemini response")

    return {
        "notes": notes,
        "topic": topic,
        "sub_topic": sub_topic,
        "title": title,
        "keywords": keywords
    }


# =========================
# Public Function: Main Entry
# =========================
def generate_study_notes_with_api(
    text: str,
    chunk_size: int = 2000,
    parallel: bool = True,
    model: str = DEFAULT_MODEL
) -> Dict[str, Any]:
    """
    Generates summarized study notes for a long text input.
    Returns:
    {
      "notes": ...,
      "title": ...,
      "topic": ...,
      "sub_topic": ...,
      "keywords": [...],
      "partials": [...]
    }
    """
    try:
        if not text or not isinstance(text, str):
            return {"notes": "", "title": "", "topic": "", "sub_topic": "", "keywords": [], "partials": []}

        # Split text into manageable chunks
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        logger.debug(f"Text length={len(text)} | Chunk size={chunk_size} | Chunks={len(chunks)}")

        # Summarize chunks
        partials: List[str] = []
        if parallel and len(chunks) > 1:
            try:
                max_workers = min(8, len(chunks))
                args_iter = ((c, model) for c in chunks)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    results = list(executor.map(_summarize_chunk, args_iter))
                    partials.extend(results)
            except Exception:
                logger.exception("Parallel summarization failed, falling back to sequential.")
                for c in chunks:
                    partials.append(_summarize_chunk((c, model)))
        else:
            for c in chunks:
                partials.append(_summarize_chunk((c, model)))

        filtered_partials = [p for p in partials if p and isinstance(p, str) and p.strip()]
        if not filtered_partials:
            fallback_text = "\n\n".join([p for p in partials if p and isinstance(p, str)]) or ""
            return {"notes": fallback_text, "title": "", "topic": "", "sub_topic": "", "keywords": [], "partials": partials}

        # Refine and merge all summaries
        result_data = _refine_and_merge_partials(filtered_partials, model=model)

        return {
            "notes": result_data.get("notes"),
            "title": result_data.get("title"),
            "topic": result_data.get("topic"),
            "sub_topic": result_data.get("sub_topic"),
            "keywords": result_data.get("keywords"),
            "partials": filtered_partials
        }

    except Exception:
        logger.exception("generate_study_notes_with_api: unexpected error")
        return {"notes": "", "title": "", "topic": "", "sub_topic": "", "keywords": [], "partials": []}
