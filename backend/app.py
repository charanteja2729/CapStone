import os
import re
import json
import traceback
from datetime import datetime
from typing import Optional, Any, Dict
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, current_app
from flask_cors import CORS
from dotenv import load_dotenv
import logging

from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
# decode_token may exist depending on flask_jwt_extended version
try:
    from flask_jwt_extended import decode_token
except Exception:
    decode_token = None

from pymongo import MongoClient, ReturnDocument
from bson.objectid import ObjectId

# --- Quiz / Summarizer imports ---
from quiz_generator import generate_quiz_with_gemini
from summarizer import generate_study_notes_with_api
from audio_extractor import get_transcript_from_url

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Load Environment Variables & Initialize ---
load_dotenv()
app = Flask(__name__)

# DEBUG flag
APP_DEBUG = os.getenv("FLASK_DEBUG", os.getenv("DEBUG", "false")).lower() in ("1", "true", "yes")
app.debug = APP_DEBUG

# Frontend origin for CORS
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# Configure CORS
CORS(
    app,
    resources={r"/api/*": {"origins": FRONTEND_ORIGIN}},
    supports_credentials=True,
)

# Add explicit CORS headers
@app.after_request
def add_cors_headers(response):
    response.headers.setdefault("Access-Control-Allow-Origin", FRONTEND_ORIGIN)
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Requested-With")
    response.headers.setdefault("Access-Control-Allow-Credentials", "true")
    return response

# Required env vars and DB config
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "please_change_this_in_prod")
api_key = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "study_app")

# --- Initialize JWT ---
jwt = JWTManager(app)

# --- Initialize MongoDB ---
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_col = db["users"]

# Global shared cache ONLY for videos
video_summaries_col = db["video_summaries"]


# -------------------------
# Helper utilities
# -------------------------
def _safe_object_id(val: Any) -> Optional[ObjectId]:
    """Return ObjectId if val is a 24-char hex string, else None."""
    if isinstance(val, ObjectId):
        return val
    if isinstance(val, str):
        try:
            return ObjectId(val)
        except Exception:
            return None
    return None


def _identity_from_authorization_header():
    """Try to decode JWT identity directly from Authorization header."""
    auth = request.headers.get('Authorization') or request.headers.get('authorization')
    if not auth:
        return None
    parts = auth.split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != 'bearer' or not token:
        return None

    if decode_token:
        try:
            decoded = decode_token(token)
            for key in ('identity', 'sub', 'user_id'):
                if key in decoded:
                    return decoded[key]
            return decoded
        except Exception:
            logger.exception("decode_token failed for Authorization header token")
            return None
    return None


def _find_user_by_identity(identity: Any):
    """Find user document given an identity which may be ObjectId string or email."""
    if not identity:
        return None
    oid = _safe_object_id(identity)
    if oid:
        return users_col.find_one({'_id': oid})
    if isinstance(identity, str):
        return users_col.find_one({'email': identity}) or users_col.find_one({'_id': identity})
    return None


def _apply_user_update(user_id: Any, update_ops: Dict, projection: Optional[Dict] = None):
    """Apply update to user document atomically and return the updated document (or None)."""
    try:
        oid = _safe_object_id(user_id) or user_id
        updated = users_col.find_one_and_update(
            {'_id': oid},
            update_ops,
            return_document=ReturnDocument.AFTER,
            projection=projection
        )
        if updated:
            return updated
        res = users_col.update_one({'_id': oid}, update_ops)
        if res.matched_count:
            return users_col.find_one({'_id': oid}, projection or {})
        return None
    except Exception:
        logger.exception('Error applying user update')
        try:
            oid = _safe_object_id(user_id) or user_id
            users_col.update_one({'_id': oid}, update_ops)
            return users_col.find_one({'_id': oid}, projection or {})
        except Exception:
            logger.exception('Final fallback update failed')
            return None


def get_user_doc_or_none():
    """Robust optional JWT verification helper."""
    try:
        try:
            from flask_jwt_extended import verify_jwt_in_request_optional
            try:
                verify_jwt_in_request_optional()
            except Exception:
                pass
        except Exception:
            try:
                from flask_jwt_extended import verify_jwt_in_request
                try:
                    verify_jwt_in_request(optional=True)  # type: ignore[arg-type]
                except TypeError:
                    try:
                        verify_jwt_in_request()
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        logger.debug("verify_jwt_in_request optional attempt failed")

    try:
        identity = get_jwt_identity()
        if identity:
            user = _find_user_by_identity(identity)
            if user:
                return user
    except Exception:
        logger.debug("get_jwt_identity did not return a usable identity")

    try:
        identity_from_header = _identity_from_authorization_header()
        if identity_from_header:
            user = _find_user_by_identity(identity_from_header)
            if user:
                return user
    except Exception:
        logger.debug("token decode from header failed")

    if current_app and current_app.debug:
        try:
            body = {}
            if request.is_json:
                body = request.get_json(silent=True) or {}
            dev_user_id = body.get('dev_user_id') or request.args.get('dev_user_id')
            dev_user_email = body.get('dev_user_email') or request.args.get('dev_user_email')
            if dev_user_id:
                oid = _safe_object_id(dev_user_id)
                if oid:
                    return users_col.find_one({'_id': oid})
                return users_col.find_one({'_id': dev_user_id})
            if dev_user_email:
                return users_col.find_one({'email': dev_user_email})
        except Exception:
            logger.exception("dev override failed")
    return None


# --- YouTube ID helper for per-video cache ---
YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|v/))([A-Za-z0-9_-]{11})"
)

def extract_youtube_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = YOUTUBE_ID_RE.search(url)
    if m:
        return m.group(1)
    try:
        parsed = urlparse(url)
        if parsed.netloc.endswith("youtube.com"):
            q = parse_qs(parsed.query)
            v = q.get("v", [])
            if v and len(v[0]) == 11:
                return v[0]
    except Exception:
        pass
    return None

# ===== END OF PART 1 =====
# -------------------------
# Routes
# -------------------------
@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


# -------------------------
# Auth endpoints
# -------------------------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or "").strip().lower()
    password = data.get('password')
    name = data.get('name', '')

    if not email or not password:
        return jsonify({'error': 'email and password are required.'}), 400

    if users_col.find_one({'email': email}):
        return jsonify({'error': 'User with that email already exists.'}), 409

    hashed = generate_password_hash(password)
    now = datetime.utcnow()
    user_doc = {
        'email': email,
        'name': name,
        'password': hashed,
        'points': 0,
        'summarize_count': 0,
        'recent_topics': [],
        'created_at': now,
        'updated_at': now
    }

    result = users_col.insert_one(user_doc)
    return jsonify({'message': 'registered successfully', 'user': {'email': email, 'name': name, 'id': str(result.inserted_id)}}), 201


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or "").strip().lower()
    password = data.get('password')

    if not email or not password:
        return jsonify({'error': 'email and password are required.'}), 400

    user = users_col.find_one({'email': email})
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    if not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    access_token = create_access_token(identity=str(user['_id']))
    return jsonify({'access_token': access_token, 'user': {'email': user['email'], 'name': user.get('name'), 'id': str(user['_id'])}})


# -------------------------
# Profile endpoint
# -------------------------
@app.route('/api/me', methods=['GET'])
@jwt_required()
def me():
    identity = get_jwt_identity()
    if not identity:
        return jsonify({'error': 'Invalid token or identity not present'}), 401

    user = _find_user_by_identity(identity)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    profile = {
        'email': user.get('email'),
        'name': user.get('name'),
        'points': user.get('points', 0),
        'summarize_count': user.get('summarize_count', 0),
        'recent_topics': user.get('recent_topics', [])[:3],
        'created_at': user.get('created_at'),
        'updated_at': user.get('updated_at')
    }
    return jsonify({'user': profile})


# -------------------------
# Summarization endpoint (TEXT) — FIXED
# -------------------------
@app.route('/api/summarize', methods=['POST', 'OPTIONS'])
def summarize_text():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    text = data.get('text')
    frontend_title = (data.get('title') or '').strip()

    if not text:
        return jsonify({'error': 'No text provided for summarization.'}), 400

    user = get_user_doc_or_none()
    logger.info("summarize (text) called — user: %s", (user.get('email') if user else None))

    try:
        summary_data = generate_study_notes_with_api(text, chunk_size=2000, parallel=True)
        final_title = frontend_title or summary_data.get("title") or "Summary"

        if user:
            try:
                saved_doc = {
                    "_id": ObjectId(),
                    "type": "text",
                    "title": final_title,
                    "notes": summary_data.get("notes") or "",
                    "created_at": datetime.utcnow()
                }

                # ✅ FIXED: merged $push so notes actually store
                users_col.update_one(
                    {"_id": user["_id"]},
                    {
                        "$push": {
                            "saved_summaries": saved_doc,
                            "recent_topics": {
                                "$each": [
                                    {"title": summary_data.get("topic") or final_title, "time": datetime.utcnow()}
                                ],
                                "$position": 0,
                                "$slice": 3
                            }
                        },
                        "$inc": {"summarize_count": 1, "points": 1},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )

            except Exception:
                logger.exception("Failed to persist text summary to user.saved_summaries")

        summary_data['title'] = final_title
        summary_data['cache_hit'] = False
        return jsonify(summary_data)

    except Exception as e:
        logger.exception('Unexpected error in summarize')
        return jsonify({'error': f'An unexpected error occurred: {e}'}), 500


# -------------------------
# Video processing endpoint (YOUTUBE) — FIXED
# -------------------------
@app.route('/api/process-video', methods=['POST', 'OPTIONS'])
def process_video():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    video_url = (data.get('video_url') or "").strip()

    if not video_url:
        return jsonify({'error': 'Video URL is required.'}), 400
    if not (video_url.startswith('http://') or video_url.startswith('https://')):
        return jsonify({'error': 'Invalid video URL.'}), 400

    user = get_user_doc_or_none()
    logger.info("process-video called — user: %s", (user.get('email') if user else None))

    try:
        video_id = extract_youtube_id(video_url)
        if not video_id:
            return jsonify({'error': 'Could not parse YouTube video id from URL.'}), 400

        # ✅ CACHE CHECK
        cached = video_summaries_col.find_one({'video_id': video_id})
        if cached:
            logger.info("Video summary cache HIT: %s", video_id)

            final_title = cached.get("title") or "Video Summary"
            resp = {
                "cache_hit": True,
                "video_id": video_id,
                "video_url": cached.get("video_url") or video_url,
                "title": final_title,
                "notes": cached.get("notes", ""),
                "topic": cached.get("topic", ""),
                "sub_topic": cached.get("sub_topic", ""),
                "keywords": cached.get("keywords", []),
            }

            # ✅ Store inline notes & award points on cache-hit (Option B)
            if user:
                try:
                    already = next((s for s in (user.get('saved_summaries') or [])
                                    if s.get('video_id') == video_id), None)
                    if not already:
                        users_col.update_one(
                            {"_id": user["_id"]},
                            {
                                "$push": {
                                    "saved_summaries": {
                                        "_id": ObjectId(),
                                        "type": "video",
                                        "video_id": video_id,
                                        "video_url": cached.get("video_url") or video_url,
                                        "title": final_title,
                                        "notes": cached.get("notes", ""),   # ✅ inline
                                        "created_at": datetime.utcnow()
                                    },
                                    "recent_topics": {
                                        "$each": [
                                            {"title": cached.get("topic") or final_title, "time": datetime.utcnow()}
                                        ],
                                        "$position": 0,
                                        "$slice": 3
                                    }
                                },
                                "$inc": {"summarize_count": 1, "points": 1},
                                "$set": {"updated_at": datetime.utcnow()}
                            }
                        )
                except Exception:
                    logger.exception("Failed to update user on cache-hit")

            return jsonify(resp)

        # ✅ NO CACHE → extract transcript + generate summary
        result = get_transcript_from_url(video_url)
        transcript = None
        extractor_title = None
        error = None
        if isinstance(result, (tuple, list)):
            if len(result) == 2:
                transcript, error = result
            elif len(result) == 3:
                transcript, extractor_title, error = result
            elif len(result) > 0:
                transcript = result[0]
        else:
            transcript = result

        if error or not transcript or not transcript.strip():
            return jsonify({'error': 'Failed to extract transcript from the provided video.'}), 500

        summary_data = generate_study_notes_with_api(transcript, chunk_size=2000, parallel=True)
        final_title = (summary_data.get("title") or extractor_title or "Video Summary")

        doc_to_insert = {
            "video_id": video_id,
            "video_url": video_url,
            "notes": summary_data.get("notes", ""),
            "title": final_title,
            "topic": summary_data.get("topic", ""),
            "sub_topic": summary_data.get("sub_topic", ""),
            "keywords": summary_data.get("keywords", []),
            "created_at": datetime.utcnow()
        }

        try:
            video_summaries_col.insert_one(doc_to_insert)
        except Exception:
            cached2 = video_summaries_col.find_one({'video_id': video_id})
            if cached2:
                doc_to_insert = cached2

        # ✅ Save to user + points (first generator)
        if user:
            try:
                users_col.update_one(
                    {"_id": user["_id"]},
                    {
                        "$push": {
                            "saved_summaries": {
                                "_id": ObjectId(),
                                "type": "video",
                                "video_id": video_id,
                                "video_url": doc_to_insert.get("video_url") or video_url,
                                "title": final_title,
                                "notes": doc_to_insert.get("notes", ""),  # ✅ same behavior as cache-hit
                                "created_at": datetime.utcnow()
                            },
                            "recent_topics": {
                                "$each": [
                                    {"title": summary_data.get("topic") or final_title, "time": datetime.utcnow()}
                                ],
                                "$position": 0,
                                "$slice": 3
                            }
                        },
                        "$inc": {"summarize_count": 1, "points": 1},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )
            except Exception:
                logger.exception("Failed to update user on fresh video summary")

        resp = {
            "cache_hit": False,
            "video_id": video_id,
            "video_url": video_url,
            "title": final_title,
            "notes": doc_to_insert.get("notes", ""),
            "topic": doc_to_insert.get("topic", ""),
            "sub_topic": doc_to_insert.get("sub_topic", ""),
            "keywords": doc_to_insert.get("keywords", []),
            "transcript": transcript
        }
        return jsonify(resp)

    except Exception:
        logger.exception('Unexpected error in process-video for url=%s', video_url)
        return jsonify({'error': 'An internal error occurred while processing the video.'}), 500


# =========================================================
# ✅ ALL OTHER ENDPOINTS BELOW ARE UNCHANGED
# =========================================================

@app.route('/api/generate-quiz', methods=['POST', 'OPTIONS'])
def generate_quiz():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    try:
        num_questions = int(data.get('num_questions', data.get('n', 10)))
    except (TypeError, ValueError):
        num_questions = 10

    if not text:
        return jsonify({'error': 'text field is required to generate a quiz.'}), 400

    user = get_user_doc_or_none()
    logger.info("generate-quiz called — user: %s", (user.get('email') if user else None))

    try:
        quiz = generate_quiz_with_gemini(text, num_questions=num_questions)
        return jsonify({'quiz': quiz})
    except Exception as e:
        logger.exception('Unexpected error in generate-quiz')
        return jsonify({'error': f'An unexpected error occurred while generating quiz: {e}'}), 500


# -------------------------
# Submit quiz — store only last 10 weak-topic entries
# -------------------------
@app.route('/api/submit-quiz', methods=['POST'])
@jwt_required()
def submit_quiz():
    data = request.get_json(silent=True) or {}
    quiz = data.get('quiz') or []
    answers = data.get('answers') or []

    if not quiz or not answers or len(quiz) != len(answers):
        return jsonify({'error': 'quiz and answers are required and must have the same length.'}), 400

    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    graded_total = 0
    correct = 0
    mistakes_docs = []
    weak_topic_docs = []

    for q, user_ans in zip(quiz, answers):
        correct_ans = q.get('correct_answer')
        question_text = (q.get('question') or q.get('prompt') or '').strip()
        topic = (q.get('topic') or 'General').strip() or 'General'

        if correct_ans is None:
            continue

        graded_total += 1
        user_ans_str = (str(user_ans) if user_ans is not None else "").strip()

        if user_ans_str.lower() == str(correct_ans).strip().lower():
            correct += 1
        else:
            mistakes_docs.append({
                'topic': topic,
                'question': question_text,
                'given': user_ans_str,
                'correct': correct_ans,
                'time': datetime.utcnow()
            })
            weak_topic_docs.append({
                'topic': topic,
                'question': question_text,
                'time': datetime.utcnow()
            })

    if graded_total == 0:
        return jsonify({'error': 'No gradable questions found in quiz.'}), 400

    if weak_topic_docs:
        try:
            users_col.update_one(
                {'_id': user['_id']},
                {
                    '$push': {
                        'incorrect_topics': {
                            '$each': weak_topic_docs,
                            '$slice': -10
                        }
                    },
                    '$set': {'updated_at': datetime.utcnow()}
                },
                upsert=False
            )
        except Exception:
            logger.exception("Failed to persist incorrect_topics")

    points_awarded = correct * 10

    return jsonify({
        'total': graded_total,
        'correct': correct,
        'points_awarded': points_awarded,
        'incorrect_preview': mistakes_docs[-10:],
    })


# -------------------------
# Saved summaries list / fetch / rename / delete
# -------------------------
@app.route('/api/my-summaries', methods=['GET'])
@jwt_required()
def list_my_summaries():
    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    items = user.get('saved_summaries') or []
    items = sorted(items, key=lambda x: x.get('created_at') or datetime.min, reverse=True)
    for it in items:
        if isinstance(it.get('_id'), ObjectId):
            it['_id'] = str(it['_id'])
    return jsonify({'saved_summaries': items})


@app.route('/api/my-summaries/<summary_id>', methods=['GET'])
@jwt_required()
def get_my_summary(summary_id):
    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    sid = _safe_object_id(summary_id)

    if sid:
        saved_list = user.get('saved_summaries') or []
        found = None
        for it in saved_list:
            if isinstance(it.get('_id'), ObjectId) and it['_id'] == sid:
                found = it
                break
            if isinstance(it.get('_id'), str) and it['_id'] == str(sid):
                found = it
                break

        if not found:
            return jsonify({'error': 'Summary not found'}), 404

        if found.get('type') == 'text' or ('notes' in found and isinstance(found.get('notes'), str)):
            out = {
                '_id': str(found['_id']),
                'type': found.get('type', 'text'),
                'title': found.get('title') or 'Summary',
                'notes': found.get('notes') or '',
                'created_at': found.get('created_at'),
            }
            return jsonify(out)

        video_id = found.get('video_id')
        if not video_id:
            return jsonify({'error': 'Summary not found'}), 404

        vdoc = video_summaries_col.find_one({'video_id': video_id})
        if not vdoc:
            return jsonify({'error': 'Summary not found for this video.'}), 404

        out = {
            '_id': str(found['_id']),
            'type': 'video',
            'video_id': video_id,
            'video_url': found.get('video_url') or vdoc.get('video_url'),
            'title': found.get('title') or vdoc.get('title') or 'Video Summary',
            'notes': vdoc.get('notes', ''),
            'topic': vdoc.get('topic', ''),
            'sub_topic': vdoc.get('sub_topic', ''),
            'keywords': vdoc.get('keywords', []),
            'created_at': found.get('created_at') or vdoc.get('created_at'),
        }
        return jsonify(out)

    video_id = summary_id
    vdoc = video_summaries_col.find_one({'video_id': video_id})
    if not vdoc:
        return jsonify({'error': 'Summary not found for this video.'}), 404

    try:
        already = next((s for s in (user.get('saved_summaries') or []) if s.get('video_id') == video_id), None)
        if not already:
            users_col.update_one(
                {'_id': user['_id']},
                {
                    '$push': {
                        'saved_summaries': {
                            '_id': ObjectId(),
                            'type': 'video',
                            'video_id': video_id,
                            'video_url': vdoc.get('video_url'),
                            'title': vdoc.get('title') or 'Video Summary',
                            'notes': vdoc.get('notes', ''),  # ✅ inline notes support
                            'created_at': datetime.utcnow()
                        }
                    },
                    '$set': {'updated_at': datetime.utcnow()}
                }
            )
    except Exception:
        logger.exception("Failed to ensure saved_summaries stub for video id=%s", video_id)

    out = {
        'type': 'video',
        'video_id': video_id,
        'video_url': vdoc.get('video_url'),
        'title': vdoc.get('title') or 'Video Summary',
        'notes': vdoc.get('notes', ''),
        'topic': vdoc.get('topic', ''),
        'sub_topic': vdoc.get('sub_topic', ''),
        'keywords': vdoc.get('keywords', []),
        'created_at': vdoc.get('created_at'),
    }
    return jsonify(out)


@app.route('/api/my-summaries/<summary_id>/rename', methods=['PATCH'])
@jwt_required()
def rename_saved_summary(summary_id):
    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}
    new_title = (data.get('title') or '').strip()
    if not new_title:
        return jsonify({'error': 'New title is required'}), 400

    sid = _safe_object_id(summary_id)
    if not sid:
        return jsonify({'error': 'Invalid summary id'}), 400

    try:
        res = users_col.update_one(
            {'_id': user['_id']},
            {'$set': {'saved_summaries.$[s].title': new_title, 'updated_at': datetime.utcnow()}},
            array_filters=[{'s._id': sid}]
        )
        if not res.matched_count:
            return jsonify({'error': 'Summary not found'}), 404
        return jsonify({'message': 'Title updated'})
    except Exception:
        logger.exception("Failed to rename saved summary")
        return jsonify({'error': 'Failed to rename summary'}), 500


@app.route('/api/my-summaries/<summary_id>', methods=['DELETE'])
@jwt_required()
def delete_saved_summary(summary_id):
    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    sid = _safe_object_id(summary_id)
    if not sid:
        return jsonify({'error': 'Invalid summary id'}), 400

    try:
        res = users_col.update_one(
            {'_id': user['_id']},
            {'$pull': {'saved_summaries': {'_id': sid}}, '$set': {'updated_at': datetime.utcnow()}}
        )
        if not res.modified_count:
            return jsonify({'error': 'Summary not found'}), 404
        return jsonify({'message': 'Deleted'})
    except Exception:
        logger.exception("Failed to delete saved summary")
        return jsonify({'error': 'Failed to delete summary'}), 500


# -------------------------
# Explain weak areas (on demand)
# -------------------------
@app.route('/api/explain-weak-areas', methods=['GET'])
@jwt_required()
def explain_weak_areas():
    user = _find_user_by_identity(get_jwt_identity())
    if not user:
        return jsonify({'error': 'User not found'}), 404

    recent = (user.get('incorrect_topics') or [])[-10:]
    seen = set()
    topics = []
    for doc in reversed(recent):
        t = (doc.get('topic') or 'General').strip() or 'General'
        if t not in seen:
            seen.add(t)
            topics.append(t)

    if not topics:
        return jsonify({'topics': [], 'explanations': {}})

    existing_map = {(e.get('topic') or '').strip(): e for e in (user.get('topic_explanations') or [])}
    missing = [t for t in topics if t not in existing_map]
    explanations = {t: (existing_map[t].get('explanation') if t in existing_map else None) for t in topics}

    if missing and os.getenv("GEMINI_API_KEY"):
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            model = genai.GenerativeModel(os.getenv("EXPLAIN_MODEL_NAME", "gemini-2.5-flash"))

            prompt = f"""
You are a tutor. For each topic below, write a short, beginner-friendly explanation in 3–5 bullet points.
Use simple language and include one quick example if relevant.
Return STRICT JSON object mapping topic → markdown explanation. No extra text.

Topics:
{json.dumps(missing, ensure_ascii=False)}

[JSON]
"""
            resp = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            raw = resp.text if getattr(resp, "text", None) else "{}"
            m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw, re.IGNORECASE)
            json_str = (m.group(1) if m else raw).strip()
            gen = json.loads(json_str)
            if isinstance(gen, dict):
                now = datetime.utcnow()
                to_store = {**existing_map}
                for k, v in gen.items():
                    k2 = (k or '').strip()
                    if not k2:
                        continue
                    explanations[k2] = v
                    to_store[k2] = {'topic': k2, 'explanation': v, 'updated_at': now}
                users_col.update_one(
                    {'_id': user['_id']},
                    {'$set': {'topic_explanations': list(to_store.values()), 'updated_at': now}}
                )
        except Exception:
            logger.exception("Failed to generate explanations for weak areas")

    return jsonify({'topics': topics, 'explanations': explanations})


# -------------------------
# Run
# -------------------------
if __name__ == '__main__':
    if not api_key:
        print("WARNING: GEMINI_API_KEY not found in .env file. Please check your .env file.")
    print(f"Connecting to MongoDB at: {MONGO_URI} | DB: {DB_NAME}")
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', debug=app.debug, port=port)
