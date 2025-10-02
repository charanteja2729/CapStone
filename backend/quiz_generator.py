# quiz_generator.py (improved)
import os
import random
import re
from collections import Counter
import logging
from typing import List, Dict, Any

# optional heavy deps
try:
    import spacy
except Exception:
    spacy = None

try:
    import nltk
    from nltk.corpus import wordnet as wn
except Exception:
    nltk = None
    wn = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Control whether runtime downloads are allowed (set in CI/container image instead)
ALLOW_MODEL_DOWNLOAD = os.getenv("ALLOW_MODEL_DOWNLOAD", "false").lower() in ("1", "true", "yes")

# --- Ensure required NLTK data is present (only if we have nltk and downloads allowed) ---
if nltk and ALLOW_MODEL_DOWNLOAD:
    try:
        nltk.data.find("corpora/wordnet")
    except LookupError:
        logger.info("Downloading NLTK wordnet data...")
        nltk.download("wordnet", quiet=True)
        nltk.download("omw-1.4", quiet=True)

# --- Initialize spaCy model (if available) ---
nlp = None
if spacy:
    try:
        nlp = spacy.load("en_core_web_sm")
        logger.info("Loaded spaCy model en_core_web_sm")
    except Exception:
        if ALLOW_MODEL_DOWNLOAD:
            try:
                import spacy.cli
                logger.info("Downloading spaCy model en_core_web_sm...")
                spacy.cli.download("en_core_web_sm")
                nlp = spacy.load("en_core_web_sm")
                logger.info("Downloaded and loaded spaCy model")
            except Exception:
                logger.exception("Failed to download spaCy model even though ALLOW_MODEL_DOWNLOAD is true")
                nlp = None
        else:
            logger.warning("spaCy model not available and ALLOW_MODEL_DOWNLOAD is false; falling back to lightweight heuristics")
            nlp = None
else:
    logger.warning("spaCy not installed; falling back to lightweight heuristics")

# Helper: lightweight sentence splitter if spaCy not available
def simple_sent_split(text: str) -> List[str]:
    # naive, split on sentence-ending punctuation — ok for fallback only
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]

def preprocess(text: str) -> Dict[str, Any]:
    """
    Return a state dict with:
      - doc (may be None if spaCy not available)
      - sentences: list of candidate sentences
      - noun_chunks: list of noun chunk strings (may be empty)
      - keywords: list of lemma keywords
    """
    if not text or not isinstance(text, str):
        return {"doc": None, "sentences": [], "noun_chunks": [], "keywords": []}

    if nlp:
        doc = nlp(text)
        sentences = [sent.text.strip() for sent in doc.sents if len(sent.text.split()) > 4]
        noun_chunks = [chunk.text for chunk in doc.noun_chunks]
        tokens = [token.lemma_.lower() for token in doc if token.is_alpha and not token.is_stop and token.pos_ in ("NOUN", "PROPN")]
        keyword_counts = Counter(tokens)
        keywords = [k for k, _ in keyword_counts.most_common(50)]
        return {"doc": doc, "sentences": sentences, "noun_chunks": noun_chunks, "keywords": keywords}
    else:
        # fallback heuristics
        sentences = [s for s in simple_sent_split(text) if len(s.split()) > 4]
        # simple noun-like extraction: capitalized multiword sequences or long words
        noun_chunks = []
        keywords = []
        words = re.findall(r'\b[A-Za-z][A-Za-z\-]+\b', text)
        freq = Counter([w.lower() for w in words if len(w) > 3])
        keywords = [k for k, _ in freq.most_common(50)]
        return {"doc": None, "sentences": sentences, "noun_chunks": noun_chunks, "keywords": keywords}

def wordnet_distractors(word: str, pos_tag: str = 'n', max_distractors: int = 3) -> List[str]:
    if wn is None:
        return []
    distractors = set()
    try:
        for syn in wn.synsets(word, pos=pos_tag):
            for lemma in syn.lemmas():
                name = lemma.name().replace('_', ' ')
                if name.lower() != word.lower():
                    distractors.add(name)
            for hyper in syn.hypernyms():
                for lemma in hyper.lemmas():
                    name = lemma.name().replace('_', ' ')
                    if name.lower() != word.lower():
                        distractors.add(name)
    except Exception:
        logger.exception("wordnet_distractors failed for word=%s", word)
        return []
    return list(distractors)[:max_distractors]

def fallback_distractors(answer: str, keywords: List[str], noun_chunks: List[str], n: int = 3) -> List[str]:
    cand = [k for k in keywords if k.lower() not in answer.lower()]
    choices = []
    for c in cand:
        if len(choices) >= n:
            break
        choices.append(c)
    for c in noun_chunks:
        if len(choices) >= n:
            break
        if c.lower() not in answer.lower() and c not in choices:
            choices.append(c)
    return [c for c in choices][:n]

def make_distractors(answer: str, state: Dict[str, Any], n: int = 3) -> List[str]:
    token = answer.strip().split()[0] if answer.strip() else ''
    wn_candidates = wordnet_distractors(token.lower(), pos_tag='n', max_distractors=n)
    if len(wn_candidates) >= n:
        return wn_candidates[:n]
    fb = fallback_distractors(answer, state.get('keywords', []), state.get('noun_chunks', []), n=n)
    combined = []
    for x in wn_candidates + fb:
        if x not in combined:
            combined.append(x)
    # final safeguard: if still too few, sample some other keywords (may duplicate)
    if len(combined) < n:
        extras = [k for k in state.get('keywords', []) if k not in combined and k.lower() not in answer.lower()]
        for e in extras:
            if len(combined) >= n:
                break
            combined.append(e)
    return combined[:n]

def select_answer_candidate(sentence: str) -> str:
    if nlp:
        s_doc = nlp(sentence)
        if s_doc.ents:
            return s_doc.ents[0].text.strip()
        chunks = sorted([c.text.strip() for c in s_doc.noun_chunks], key=len, reverse=True)
        if chunks:
            return chunks[0]
        nouns = [t.text for t in s_doc if t.pos_ in ("NOUN", "PROPN")]
        return nouns[0] if nouns else None
    else:
        # lightweight heuristic: choose longest capitalized phrase or longest word>4 chars
        caps = re.findall(r'\b[A-Z][a-z]{3,}(?:\s+[A-Z][a-z]{3,})*', sentence)
        if caps:
            return caps[0].strip()
        words = re.findall(r'\b[A-Za-z]{4,}\b', sentence)
        return words[0] if words else None

def make_mcq_from_sentence(sentence: str, state: Dict[str, Any], n_distractors: int = 3) -> Dict[str, Any]:
    ans = select_answer_candidate(sentence)
    if not ans:
        return None
    ans = ans.strip()
    # avoid very short answers or those at the start
    first_two = [w.lower() for w in sentence.split()[:2]]
    if ans.lower() in first_two:
        return None
    try:
        pattern = re.compile(re.escape(ans), flags=re.IGNORECASE)
        q_text = pattern.sub("______", sentence, count=1)
    except Exception:
        q_text = sentence.replace(ans, "______", 1)
    distractors = make_distractors(ans, state, n=n_distractors)
    options = [ans] + distractors
    options = list(dict.fromkeys([opt.strip() for opt in options if opt and isinstance(opt, str)]))
    if len(options) < 2:
        return None
    random.shuffle(options)
    topic = (state.get('keywords') or [None])[0] or ''
    return {
        "type": "mcq",
        "question": q_text,
        "options": options,
        "answer": ans,
        "correct_answer": ans,
        "topic": topic
    }

def make_tf_from_sentence(sentence: str, state: Dict[str, Any], false_prob: float = 0.5) -> Dict[str, Any]:
    if random.random() > false_prob:
        topic = (state.get('keywords') or [None])[0] or ''
        return {"type": "tf", "question": sentence, "answer": "True", "correct_answer": "True", "topic": topic}
    if nlp:
        s_doc = nlp(sentence)
        swap_target = None
        if s_doc.ents:
            swap_target = s_doc.ents[0].text
        else:
            chunks = [c.text for c in s_doc.noun_chunks]
            swap_target = chunks[0] if chunks else None
    else:
        ents = re.findall(r'\b[A-Z][a-z]{3,}(?:\s+[A-Z][a-z]{3,})*', sentence)
        swap_target = ents[0] if ents else None
    if not swap_target:
        topic = (state.get('keywords') or [None])[0] or ''
        return {"type": "tf", "question": sentence, "answer": "True", "correct_answer": "True", "topic": topic}
    distractors = make_distractors(swap_target, state, n=5)
    if not distractors:
        topic = (state.get('keywords') or [None])[0] or ''
        return {"type": "tf", "question": sentence, "answer": "True", "correct_answer": "True", "topic": topic}
    replacement = random.choice(distractors)
    try:
        pattern = re.compile(re.escape(swap_target), flags=re.IGNORECASE)
        false_statement = pattern.sub(replacement, sentence, count=1)
    except Exception:
        false_statement = sentence.replace(swap_target, replacement, 1)
    topic = (state.get('keywords') or [None])[0] or ''
    return {"type": "tf", "question": false_statement, "answer": "False", "correct_answer": "False", "topic": topic}

def create_quiz_from_text(text: str, num_questions: int = 10) -> List[Dict[str, Any]]:
    state = preprocess(text)
    candidates = []
    for sent in state["sentences"]:
        mcq = make_mcq_from_sentence(sent, state)
        if mcq:
            candidates.append(mcq)
        if random.random() < 0.5:
            tf = make_tf_from_sentence(sent, state)
            if tf:
                candidates.append(tf)
    random.shuffle(candidates)
    final_quiz = []
    seen_questions = set()
    for q in candidates:
        if len(final_quiz) >= num_questions:
            break
        q_text = (q.get("question") or "").strip().lower()
        if q_text and q_text not in seen_questions:
            seen_questions.add(q_text)
            if "correct_answer" not in q and "answer" in q:
                q["correct_answer"] = q["answer"]
            final_quiz.append(q)
    logger.debug("create_quiz_from_text: generated %d questions (requested %d)", len(final_quiz), num_questions)
    return final_quiz
