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

# local module imports
from summarizer import generate_study_notes_with_api, get_cache_keywords
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

# Configure CORS
CORS(app,
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
# --- [NEW] Global cache collection ---
summary_cache_col = db["summary_cache"]


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


# --- [NEW HELPER FUNCTION] ---
def _get_or_create_summary(text: str) -> Dict[str, Any]:
    """
    Central function to check cache or generate new summary.
    Returns a dictionary with the summary data and a 'cache_hit' flag.
    """
    if not text:
        return {"notes": "", "title": "", "topic": "", "sub_topic": "", "keywords": [], "cache_hit": False}

    try:
        # 1. Get cache keys from the raw text
        cache_keys = get_cache_keywords(text)
        
        if not cache_keys:
            logger.warning("Could not extract cache keys from text. Skipping cache check.")
            raise Exception("No cache keys") # Force cache miss

        # 2. Check the cache
        # We use $all to ensure all keywords are present
        cached_doc = summary_cache_col.find_one({"keywords": {"$all": cache_keys}})
        
        if cached_doc:
            logger.info(f"CACHE HIT for keywords: {cache_keys}")
            # Return a consistent dictionary structure
            return {
                "notes": cached_doc.get("notes"),
                "title": cached_doc.get("title"),
                "topic": cached_doc.get("topic"),
                "sub_topic": cached_doc.get("sub_topic"),
                "keywords": cached_doc.get("keywords"),
                "cache_hit": True
            }
    
        # 3. Cache Miss: Generate new summary
        logger.info(f"CACHE MISS for keywords: {cache_keys}. Generating new summary.")
        res = generate_study_notes_with_api(text, chunk_size=2000, parallel=True)
        
        # 4. Save to cache (only if valid)
        new_keywords = res.get("keywords")
        new_notes = res.get("notes")
        
        if new_keywords and new_notes:
            new_entry = {
                "notes": new_notes,
                "title": res.get("title"),
                "topic": res.get("topic"),
                "sub_topic": res.get("sub_topic"),
                "keywords": new_keywords, # Use the keywords from the summary
                "created_at": datetime.utcnow()
            }
            try:
                summary_cache_col.insert_one(new_entry)
                logger.info(f"Saved new entry to cache with keywords: {new_keywords}")
            except Exception:
                logger.exception("Failed to save new entry to cache")
        else:
            logger.warning("Generated summary missing notes or keywords. Not saving to cache.")

        res['cache_hit'] = False
        return res

    except Exception as e:
        logger.exception("Error in _get_or_create_summary. Falling back to simple generation.")
        # Fallback: just generate without caching
        res = generate_study_notes_with_api(text, chunk_size=2000, parallel=True)
        res['cache_hit'] = False # Indicate it was not from cache
        return res


# -------------------------
# Routes
# -------------------------
@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


# -------------------------
# Auth endpoints (Unchanged)
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
# Profile endpoint (Unchanged)
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
# Summarization endpoint [REPLACED]
# -------------------------
@app.route('/api/summarize', methods=['POST', 'OPTIONS'])
def summarize_text():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    text = data.get('text')
    frontend_title = data.get('title') # User's custom title

    if not text:
        return jsonify({'error': 'No text provided for summarization.'}), 400

    user = get_user_doc_or_none()
    logger.info("summarize called — detected user: %s", (user.get('email') if user else None))

    try:
        # --- [NEW CACHING LOGIC] ---
        # This function checks cache first, or generates new if miss
        summary_data = _get_or_create_summary(text)
        # summary_data now contains: {notes, title, topic, sub_topic, keywords, cache_hit}
        # --- [END NEW LOGIC] ---

        # Use the user's title if provided, otherwise the one from the summary
        final_title = (frontend_title or '').strip() or summary_data.get("title")

        if user:
            # Only update points/recent topics if it was a NEW generation (cache miss)
            if not summary_data.get("cache_hit"):
                inc_points = 1
                update_fields = {
                    '$inc': {'summarize_count': 1, 'points': inc_points},
                    '$set': {'updated_at': datetime.utcnow()}
                }
                
                # Use the academic topic for recent_topics
                topic_to_log = summary_data.get("topic") or final_title # Fallback
                
                if topic_to_log:
                    update_fields['$push'] = {
                        'recent_topics': {
                            '$each': [
                                {
                                    'title': topic_to_log,
                                    'time': datetime.utcnow()
                                }
                            ],
                            '$position': 0,
                            '$slice': 3
                        }
                    }
                
                updated = _apply_user_update(user['_id'], update_fields, projection={'points': 1, 'summarize_count': 1, 'recent_topics': 1})
                logger.info('summarize (cache miss) update result present? %s', bool(updated))
            else:
                logger.info("summarize (cache hit) - no points awarded.")

        # Return the summary data, replacing 'title' with our final_title
        summary_data['title'] = final_title
        return jsonify(summary_data)

    except Exception as e:
        logger.exception('Unexpected error in summarize')
        return jsonify({'error': f'An unexpected error occurred: {e}'}), 500


# -------------------------
# Video processing endpoint [REPLACED]
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
    logger.info("process-video called — detected user: %s", (user.get('email') if user else None))

    try:
        # 1. Get Transcript
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
        if error:
            logger.warning("process-video: transcript extraction failed for url=%s error=%s", video_url, error)
            return jsonify({'error': 'Failed to extract transcript from the provided video.'}), 500
        if not transcript or not isinstance(transcript, str) or not transcript.strip():
            logger.warning("process-video: empty transcript for url=%s", video_url)
            return jsonify({'error': 'Transcript is empty or unavailable for this video.'}), 500

        # --- [NEW CACHING LOGIC] ---
        # 2. Get or Create Summary from transcript
        summary_data = _get_or_create_summary(transcript)
        # --- [END NEW LOGIC] ---

        # Use video title first, then AI title
        final_title = (extractor_title or '').strip() or summary_data.get("title")

        # 3. Create quiz (from the cached or new notes)
        # Per your request, we are NO LONGER auto-generating the quiz.
        # This block is removed.
        # quiz = []

        # 4. Update user record (if any)
        if user:
            # Only update points/recent topics if it was a NEW generation (cache miss)
            if not summary_data.get("cache_hit"):
                inc_points = 1 # Your request from last time
                update_fields = {
                    '$inc': {'summarize_count': 1, 'points': inc_points},
                    '$set': {'updated_at': datetime.utcnow()}
                }
                
                # Use academic topic for recent_topics
                topic_to_log = summary_data.get("topic") or final_title # Fallback

                if topic_to_log:
                    update_fields['$push'] = {
                        'recent_topics': {
                            '$each': [
                                {
                                    'title': topic_to_log,
                                    'time': datetime.utcnow()
                                }
                            ],
                            '$position': 0,
                            '$slice': 3
                        }
                    }
                
                updated = _apply_user_update(user['_id'], update_fields, projection={'points': 1, 'summarize_count': 1, 'recent_topics': 1})
                logger.info('process-video (cache miss) update result present? %s', bool(updated))
            else:
                logger.info("process-video (cache hit) - no points awarded.")

        # 5. Return all data
        # We'll merge the summary_data with the other parts
        response_data = {
            **summary_data,
            'transcript': transcript,
            'title': final_title, # Override with our combined title
            # 'quiz': quiz # This is removed per your request
        }
        
        return jsonify(response_data)

    except Exception:
        logger.exception('Unexpected error in process-video for url=%s', video_url)
        return jsonify({'error': 'An internal error occurred while processing the video.'}), 500


# -------------------------
# Generate quiz endpoint [MODIFIED]
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
        
        # Per your request, no points for generating a quiz.
        # The if user: block that awarded points has been removed.

        return jsonify({'quiz': quiz})

    except Exception as e:
        logger.exception('Unexpected error in generate-quiz')
        return jsonify({'error': f'An unexpected error occurred while generating quiz: {e}'}), 500


# -------------------------
# Submit quiz results endpoint [MODIFIED]
# -------------------------
@app.route('/api/submit-quiz', methods=['POST'])
@jwt_required()
def submit_quiz():
    # --- MODIFIED ---
    # Per your request, this function is now "read-only".
    # It calculates the score but does NOT contact the database.
    # --- END MODIFICATION ---

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
        
        # Check answer
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

    # We still calculate points_awarded to show the user in the alert
    # We just DON'T save them to the database
    points_awarded = correct * 10

    # --- ALL DATABASE UPDATE LOGIC IS REMOVED ---

    # Return a simple response for the frontend alert
    resp = {
        'total': graded_total,
        'correct': correct,
        'points_awarded': points_awarded,
        'incorrect_preview': incorrect_list[-10:],
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