# app.py (corrected & improved)
# - Use find_one_and_update for robust, atomic updates
# - Centralized _apply_user_update helper to ensure updates persist
# - Keep same public API / behavior as before

import os
import traceback
from datetime import datetime
from typing import Optional, Any, Dict

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

# local module imports (keep names as your project expects)
from summarizer import generate_study_notes_with_api
from quiz_generator import create_quiz_from_text
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

# Configure CORS for the API routes
CORS(app,
     resources={r"/api/*": {"origins": FRONTEND_ORIGIN}},
     supports_credentials=True,
)

# Add explicit CORS headers for safety (helps when some middleware returns early)
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
    """Try to decode JWT identity directly from Authorization header.

    This is a best-effort helper for cases where library optional helpers
    are not available. Returns identity or None.
    """
    auth = request.headers.get('Authorization') or request.headers.get('authorization')
    if not auth:
        return None
    parts = auth.split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != 'bearer' or not token:
        return None

    # Try to decode token if decode_token is available
    if decode_token:
        try:
            decoded = decode_token(token)
            # Most versions put identity in one of these keys
            for key in ('identity', 'sub', 'user_id'):
                if key in decoded:
                    return decoded[key]
            return decoded
        except Exception:
            logger.exception("decode_token failed for Authorization header token")
            return None

    return None


def _find_user_by_identity(identity: Any):
    """Find user document given an identity which may be ObjectId string or email.

    Returns user document or None.
    """
    if not identity:
        return None
    oid = _safe_object_id(identity)
    if oid:
        return users_col.find_one({'_id': oid})
    if isinstance(identity, str):
        return users_col.find_one({'email': identity}) or users_col.find_one({'_id': identity})
    return None


def _apply_user_update(user_id: Any, update_ops: Dict, projection: Optional[Dict] = None):
    """Apply update to user document atomically and return the updated document (or None).

    Fallbacks to update_one if find_one_and_update doesn't return a document (robustness for older drivers / configs).
    """
    try:
        # Ensure we have an ObjectId for the query if possible
        oid = _safe_object_id(user_id) or user_id
        updated = users_col.find_one_and_update(
            {'_id': oid},
            update_ops,
            return_document=ReturnDocument.AFTER,
            projection=projection
        )
        if updated:
            return updated
        # fallback: try update_one then re-fetch
        res = users_col.update_one({'_id': oid}, update_ops)
        if res.matched_count:
            return users_col.find_one({'_id': oid}, projection or {})
        return None
    except Exception:
        logger.exception('Error applying user update')
        try:
            # final fallback: try update_one and ignore result
            oid = _safe_object_id(user_id) or user_id
            users_col.update_one({'_id': oid}, update_ops)
            return users_col.find_one({'_id': oid}, projection or {})
        except Exception:
            logger.exception('Final fallback update failed')
            return None


def get_user_doc_or_none():
    """
    Robust optional JWT verification:
      1) Try verify_jwt_in_request_optional if available / works
      2) Try verify_jwt_in_request(optional=True) (some versions)
      3) Try to decode token from Authorization header directly
      4) As a last resort in DEBUG, accept dev_user_id or dev_user_email from request data for convenience

    Returns user document or None.
    """
    # 1) Try library helpers (best effort)
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
        logger.debug("verify_jwt_in_request optional attempt failed or not available")

    # 2) Try get_jwt_identity
    try:
        identity = get_jwt_identity()
        if identity:
            user = _find_user_by_identity(identity)
            if user:
                return user
    except Exception:
        logger.debug("get_jwt_identity did not return a usable identity")

    # 3) Try decoding Authorization header directly
    try:
        identity_from_header = _identity_from_authorization_header()
        if identity_from_header:
            user = _find_user_by_identity(identity_from_header)
            if user:
                return user
    except Exception:
        logger.debug("token decode from header failed")

    # 4) Developer convenience for local testing only
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
    # nothing found
    return None


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
        'incorrect_answers': [],
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
        'incorrect_answers': user.get('incorrect_answers', [])[-20:],
        'created_at': user.get('created_at'),
        'updated_at': user.get('updated_at')
    }
    return jsonify({'user': profile})


# -------------------------
# Summarization endpoint
# -------------------------
@app.route('/api/summarize', methods=['POST', 'OPTIONS'])
def summarize_text():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    text = data.get('text')
    frontend_title = data.get('title')
    quick = bool(data.get('quick', False))

    if not text:
        return jsonify({'error': 'No text provided for summarization.'}), 400

    user = get_user_doc_or_none()
    logger.info("summarize called — detected user: %s", (user.get('email') if user else None))

    try:
        res = generate_study_notes_with_api(text, chunk_size=2000, parallel=True, quick_title_only=quick)

        notes = res.get('notes', '') if isinstance(res, dict) else (res or '')
        title = res.get('title', '') if isinstance(res, dict) else ''
        partials = res.get('partials', []) if isinstance(res, dict) else []

        final_title = (frontend_title or '').strip() or (title or '')

        if user:
            inc_points = 1
            update_fields = {
                '$inc': {'summarize_count': 1, 'points': inc_points},
                '$set': {'updated_at': datetime.utcnow()}
            }
            if final_title:
                update_fields['$push'] = {
                    'recent_topics': {
                        '$each': [
                            {
                                'title': final_title,
                                'time': datetime.utcnow()
                            }
                        ],
                        '$position': 0,
                        '$slice': 3
                    }
                }

            # apply update atomically and fetch updated doc for verification
            updated = _apply_user_update(user['_id'], update_fields, projection={'points': 1, 'summarize_count': 1, 'recent_topics': 1})
            logger.info('summarize update result present? %s', bool(updated))

        if quick:
            return jsonify({'title': final_title, 'partials': partials})

        return jsonify({'notes': notes, 'title': final_title})

    except Exception as e:
        logger.exception('Unexpected error in summarize')
        return jsonify({'error': f'An unexpected error occurred: {e}'}), 500


# -------------------------
# Video processing endpoint
@app.route('/api/process-video', methods=['POST', 'OPTIONS'])
def process_video():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    video_url = (data.get('video_url') or "").strip()
    quick = bool(data.get('quick', False))

    if not video_url:
        return jsonify({'error': 'Video URL is required.'}), 400

    # Basic URL sanity check (you can tighten this to only allow youtube domains)
    if not (video_url.startswith('http://') or video_url.startswith('https://')):
        return jsonify({'error': 'Invalid video URL.'}), 400

    user = get_user_doc_or_none()
    logger.info("process-video called — detected user: %s", (user.get('email') if user else None))

    try:
        # get_transcript_from_url may return (transcript, error) or just transcript
        result = get_transcript_from_url(video_url)

        # Normalize result to (transcript, extractor_title, error)
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

        # If gemini/download returned an error, surface a friendly message
        if error:
            logger.warning("process-video: transcript extraction failed for url=%s error=%s", video_url, error)
            return jsonify({'error': 'Failed to extract transcript from the provided video.'}), 500

        # Ensure we actually have transcript content
        if not transcript or not isinstance(transcript, str) or not transcript.strip():
            logger.warning("process-video: empty transcript for url=%s", video_url)
            return jsonify({'error': 'Transcript is empty or unavailable for this video.'}), 500

        # Generate notes & title
        res = generate_study_notes_with_api(transcript, chunk_size=2000, parallel=True, quick_title_only=quick)
        notes = res.get('notes', '') if isinstance(res, dict) else (res or '')
        title = res.get('title', '') if isinstance(res, dict) else ''
        partials = res.get('partials', []) if isinstance(res, dict) else []

        final_title = (extractor_title or '').strip() or (title or '')

        # Create quiz (best-effort, non-blocking to the response logic)
        try:
            quiz = create_quiz_from_text(transcript)
        except Exception:
            logger.exception('create_quiz_from_text failed for url=%s', video_url)
            quiz = []

        # Update user record (if any)
        if user:
            inc_points = 2
            update_fields = {
                '$inc': {'summarize_count': 1, 'points': inc_points},
                '$set': {'updated_at': datetime.utcnow()}
            }
            if final_title:
                update_fields['$push'] = {
                    'recent_topics': {
                        '$each': [
                            {
                                'title': final_title,
                                'time': datetime.utcnow()
                            }
                        ],
                        '$position': 0,
                        '$slice': 3
                    }
                }

            updated = _apply_user_update(user['_id'], update_fields, projection={'points': 1, 'summarize_count': 1, 'recent_topics': 1})
            logger.info('process-video update result present? %s', bool(updated))

        # Return either quick or full response
        if quick:
            return jsonify({'title': final_title, 'partials': partials, 'quiz': quiz})

        return jsonify({
            'transcript': transcript,
            'notes': notes,
            'title': final_title,
            'quiz': quiz
        })

    except Exception:
        # Log detailed exception server-side but return a generic message to clients
        logger.exception('Unexpected error in process-video for url=%s', video_url)
        return jsonify({'error': 'An internal error occurred while processing the video.'}), 500


# -------------------------
# Generate quiz endpoint
# -------------------------
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
    logger.info("generate-quiz called — detected user: %s", (user.get('email') if user else None))

    try:
        quiz = create_quiz_from_text(text, num_questions=num_questions)

        if user:
            update_fields = {
                '$inc': {'points': 1},
                '$set': {'updated_at': datetime.utcnow()}
            }
            updated = _apply_user_update(user['_id'], update_fields, projection={'points': 1})
            logger.info('generate-quiz update result present? %s', bool(updated))

        return jsonify({'quiz': quiz})

    except Exception as e:
        logger.exception('Unexpected error in generate-quiz')
        return jsonify({'error': f'An unexpected error occurred while generating quiz: {e}'}), 500


# -------------------------
# Submit quiz results endpoint
# -------------------------
@app.route('/api/submit-quiz', methods=['POST'])
@jwt_required()
def submit_quiz():
    identity = get_jwt_identity()
    user = _find_user_by_identity(identity)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}
    quiz = data.get('quiz') or []
    answers = data.get('answers') or []

    if not quiz or not answers or len(quiz) != len(answers):
        return jsonify({'error': 'quiz and answers are required and must have the same length.'}), 400

    graded_total = 0
    correct = 0
    incorrect_list = []

    for q, user_ans in zip(quiz, answers):
        correct_ans = q.get('correct_answer')
        question_text = q.get('question') or q.get('prompt') or ''
        if correct_ans is None:
            continue
        graded_total += 1
        if str(user_ans).strip().lower() == str(correct_ans).strip().lower():
            correct += 1
        else:
            incorrect_list.append({
                'question': question_text,
                'given': user_ans,
                'correct': correct_ans,
                'time': datetime.utcnow()
            })

    if graded_total == 0:
        return jsonify({'error': 'No gradable questions found in quiz.'}), 400

    points_awarded = correct * 10

    update_ops = {
        '$inc': {'points': points_awarded},
        '$set': {'updated_at': datetime.utcnow()}
    }

    push_map = {}
    MAX_INCORRECT_KEEP = 200

    # DO NOT add individual incorrect questions to DB by default.
    low_score = (correct / graded_total) < 0.5

    topic_name = ''
    topic_added = False

    if low_score:
        # Prefer explicit topic provided in request, otherwise try to derive from quiz
        topic_name = (data.get('topic') or data.get('title') or '').strip()
        if not topic_name and isinstance(quiz, list) and len(quiz) > 0:
            first = quiz[0]
            topic_name = (first.get('topic') or first.get('title') or first.get('prompt') or '').strip()

        if topic_name:
            topic_entry = {
                'question': f'Topic: {topic_name}',
                'given': '',
                'correct': '',
                'time': datetime.utcnow()
            }
            push_map['incorrect_answers'] = {'$each': [topic_entry], '$slice': -MAX_INCORRECT_KEEP}

            recent_topic_push = {
                'title': topic_name,
                'time': datetime.utcnow()
            }
            push_map['recent_topics'] = {
                '$each': [recent_topic_push],
                '$position': 0,
                '$slice': 3
            }

    if push_map:
        update_ops['$push'] = push_map

    # Log what we're about to do so we can debug why DB didn't change
    try:
        logger.info(
            "submit-quiz: user_id=%s graded_total=%d correct=%d low_score=%s topic_name=%s update_ops=%s",
            str(user.get('_id')), graded_total, correct, low_score, topic_name, update_ops
        )
    except Exception:
        logger.debug("submit-quiz: failed to log update details")

    # Use centralized helper for robust update + fallback behavior
    try:
        updated = _apply_user_update(user['_id'], update_ops, projection={'points': 1, 'recent_topics': 1, 'incorrect_answers': 1})
        if not updated:
            logger.warning('submit-quiz: update returned no document for _id=%s', user['_id'])
            # try one more raw attempt to surface errors in logs
            try:
                users_col.update_one({'_id': user['_id']}, update_ops)
                updated = users_col.find_one({'_id': user['_id']}, {'points': 1, 'recent_topics': 1, 'incorrect_answers': 1})
            except Exception:
                logger.exception('submit-quiz: second attempt update_one failed')
                return jsonify({'error': 'Failed to update user results.'}), 500

    except Exception:
        logger.exception('Error updating user during submit-quiz via helper')
        return jsonify({'error': 'Failed to update user results.'}), 500

    # Check if topic was actually added (defensive)
    try:
        incorrect_answers = updated.get('incorrect_answers') or []
        recent_topics = updated.get('recent_topics') or []
        if topic_name:
            # presence test — we expect at least one element whose 'question' contains the topic string
            for item in incorrect_answers[-5:]:
                qtext = (item.get('question') or '') if isinstance(item, dict) else ''
                if topic_name in qtext:
                    topic_added = True
                    break
        logger.info("submit-quiz: topic_added=%s incorrect_count=%d recent_topics_count=%d", topic_added, len(incorrect_answers), len(recent_topics))
    except Exception:
        logger.exception("submit-quiz: error while verifying updated document")

    resp = {
        'total': graded_total,
        'correct': correct,
        'points_awarded': points_awarded,
        'points': updated.get('points', None),
        'recent_topics': (updated.get('recent_topics') or [])[:3],
        'incorrect_preview': incorrect_list[-10:],
        # helpful debugging fields (remove in prod if you like)
        'topic_sent': topic_name,
        'topic_added': topic_added
    }

    return jsonify(resp)


# -------------------------
# Run
# -------------------------
if __name__ == '__main__':
    if not api_key:
        print("WARNING: GEMINI_API_KEY not found in .env file. Please check your .env file.")
    print(f"Connecting to MongoDB at: {MONGO_URI} | DB: {DB_NAME}")
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', debug=app.debug, port=port)
