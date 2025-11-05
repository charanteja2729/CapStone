# quiz_generator.py (Gemini-based MCQ generator)
import os
import re
import json
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("QUIZ_MODEL_NAME", "gemini-2.5-flash")

if API_KEY:
    try:
        genai.configure(api_key=API_KEY)
        logger.info("Gemini API configured for quiz generation.")
    except Exception:
        logger.exception("Failed to configure Gemini for quiz generation.")
else:
    logger.warning("GEMINI_API_KEY not set. Quiz generation will fallback to empty list.")


def _extract_json_array(text: str) -> str:
    """Extract a JSON array from raw model text or fenced ```json blocks."""
    if not text:
        return "[]"
    # Try fenced code block
    m = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Try any array-looking content
    m2 = re.search(r"(\[[\s\S]*\])", text)
    return (m2.group(1).strip() if m2 else "[]")


def _validate_mcq_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the MCQ has required fields and is clean."""
    q = (item.get("question") or "").strip()
    options = item.get("options") or []
    options = [str(o).strip() for o in options if str(o).strip()]
    correct = (item.get("correct_answer") or "").strip()
    topic = (item.get("topic") or "").strip() or "General"

    # must-haves
    if not q or not options or not correct:
        return {}

    # ensure correct in options; if not, insert at random end
    if correct not in options:
        options = options[:]
        options.append(correct)

    # keep at most 6 options & at least 2
    options = list(dict.fromkeys(options))[:6]  # dedupe, cap at 6
    if len(options) < 2:
        return {}

    return {
        "type": "mcq",
        "question": q,
        "options": options,
        "correct_answer": correct,
        "topic": topic
    }


def generate_quiz_with_gemini(text: str, num_questions: int = 10) -> List[Dict[str, Any]]:
    """
    Generate ONLY MCQs using Gemini. Returns list of items:
    {
      "type": "mcq",
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "B",
      "topic": "Operating Systems"
    }
    """
    if not API_KEY:
        logger.warning("No API key configured. Returning empty quiz.")
        return []

    text = (text or "").strip()
    if not text:
        return []

    prompt = f"""
You are an expert educator. Create ONLY multiple-choice questions from the material below.

Requirements:
- Return a JSON array of objects.
- Each object MUST have: "question", "options" (3-5 strings), "correct_answer", and "topic".
- "topic" should be the specific sub-topic (e.g., "Deadlocks", "HashMap", "DFS"), not just "Computer Science".
- Do NOT include explanations or difficulty.
- The output MUST be valid JSON ONLY (no extra text).

Number of questions: {num_questions}

[Material]
{text}

[JSON]
"""

    try:
        model = genai.GenerativeModel(MODEL)
        resp = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        raw = resp.text if getattr(resp, "text", None) else ""
        json_str = _extract_json_array(raw)
        data = json.loads(json_str)
        if not isinstance(data, list):
            return []

        cleaned: List[Dict[str, Any]] = []
        for item in data:
            fixed = _validate_mcq_item(item if isinstance(item, dict) else {})
            if fixed:
                cleaned.append(fixed)

        # Cap to requested number
        return cleaned[:num_questions]

    except Exception:
        logger.exception("generate_quiz_with_gemini failed")
        return []
