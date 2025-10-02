"""
python_api/audio_extractor.py

Downloads audio from a YouTube URL (using yt_dlp + ffmpeg), uploads it to
the Gemini/Vertex generative API and requests a verbatim transcription.

Public:
- get_transcript_from_url(url) -> (transcript: str | None, error: str | None)

Notes:
- Requires `ffmpeg` on PATH (for yt_dlp postprocessing).
- Requires GEMINI_API_KEY in environment for transcription.
- Configure MODEL_NAME in .env to a model available in your GCP project.
"""
import os
import traceback
import tempfile
import shutil
import logging
from typing import Tuple, Optional

import yt_dlp
import google.generativeai as genai

# Configure logger for this module
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Read model name from env so we can change easily if model is retired/unavailable
MODEL_NAME = os.getenv("MODEL_NAME", "models/gemini-2.5-flash")


def _ensure_genai_configured() -> bool:
    """
    Configure google.generativeai with GEMINI_API_KEY from environment.
    Returns True if configured, False otherwise.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        logger.warning("GEMINI_API_KEY not found in environment.")
        return False
    try:
        # genai.configure(api_key=...) is the usual pattern; adjust if SDK differs
        genai.configure(api_key=key)
        logger.debug("Configured google.generativeai with API key.")
        return True
    except Exception as e:
        logger.exception("Failed to configure google.generativeai: %s", e)
        return False


def _ensure_ffmpeg_available() -> bool:
    """Check ffmpeg is available on PATH (required by yt_dlp postprocessor)."""
    from shutil import which

    if which("ffmpeg") is None:
        logger.warning("ffmpeg not found on PATH. yt_dlp postprocessing may fail.")
        return False
    return True


def _download_audio_from_youtube(youtube_url: str, work_dir: str) -> str:
    """
    Download audio from YouTube and convert to WAV.
    Returns path to the WAV file.

    Tries a yt_dlp postprocessor first; on DownloadError, falls back to
    downloading the audio file as-is and converting with ffmpeg manually.
    Raises Exception on failure.
    """
    import subprocess
    from yt_dlp.utils import DownloadError

    os.makedirs(work_dir, exist_ok=True)
    outtmpl = os.path.join(work_dir, "temp_audio.%(ext)s")

    # Primary attempt: let yt_dlp do the extraction + ffmpeg conversion
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
    }

    logger.info("Starting audio download for URL: %s", youtube_url)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
    except DownloadError as e:
        # Specific yt_dlp download error: try fallback strategy
        logger.warning("yt_dlp DownloadError: %s — attempting fallback download+ffmpeg convert", e)
        # Fallback: download best audio without postprocessing, then convert with ffmpeg
        fallback_opts = {
            "format": "bestaudio",
            "outtmpl": outtmpl,  # e.g. temp_audio.webm or temp_audio.m4a
            "noplaylist": True,
            "quiet": False,      # show more info for diagnostics in fallback
            "no_warnings": False,
            # Do not use postprocessors here
        }
        try:
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                # find downloaded filename from info or glob
                # If extract_info returned a filename, good; otherwise search the directory
        except Exception as e2:
            logger.exception("Fallback yt_dlp download also failed: %s", e2)
            raise

        # At this point find any file starting with temp_audio
        downloaded = None
        for candidate in os.listdir(work_dir):
            if candidate.startswith("temp_audio"):
                downloaded = os.path.join(work_dir, candidate)
                break

        if not downloaded:
            raise FileNotFoundError("Fallback download succeeded but no temp_audio.* file found.")

        # Now convert to WAV using ffmpeg (explicit, separate process)
        wav_path = os.path.join(work_dir, "temp_audio.wav")
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found on PATH; cannot convert audio to WAV.")

        cmd = [
            "ffmpeg",
            "-y",  # overwrite
            "-i", downloaded,
            "-ar", "16000",  # set sample rate if desired
            "-ac", "1",      # mono
            wav_path
        ]
        logger.info("Running ffmpeg to convert downloaded audio -> WAV: %s", " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error("ffmpeg failed: stdout=%s stderr=%s", res.stdout, res.stderr)
            raise RuntimeError(f"ffmpeg conversion failed: {res.stderr[:200]}")

        if os.path.exists(wav_path):
            logger.info("Fallback conversion produced WAV: %s", wav_path)
            return wav_path
        else:
            raise FileNotFoundError("ffmpeg conversion reported success but WAV not found.")

    except Exception:
        # Any other exception in the primary attempt
        logger.exception("yt_dlp failed to download/convert audio: %s", youtube_url)
        raise

    # Primary path expected WAV
    expected_wav = os.path.join(work_dir, "temp_audio.wav")
    if os.path.exists(expected_wav):
        logger.info("Downloaded and converted audio to WAV: %s", expected_wav)
        return expected_wav

    # If not present, try to find any file beginning with temp_audio
    for candidate in os.listdir(work_dir):
        if candidate.startswith("temp_audio"):
            candidate_path = os.path.join(work_dir, candidate)
            if os.path.isfile(candidate_path):
                logger.info("Found audio file candidate: %s", candidate_path)
                return candidate_path

    raise FileNotFoundError("Audio download/conversion failed: temp_audio.* not found in work dir.")


def _transcribe_audio_with_gemini(audio_path: str, timeout_seconds: int = 600) -> str:
    """
    Uploads audio file to Gemini and requests a verbatim transcription.
    Returns the transcript text.

    Raises RuntimeError on failure or ValueError when API key is missing or SDK lacks upload API.
    """
    if not _ensure_genai_configured():
        raise ValueError("Gemini API key is not configured. Set GEMINI_API_KEY in environment.")

    logger.info("Using model '%s' for transcription.", MODEL_NAME)

    # Check whether SDK has upload_file helper
    if not hasattr(genai, "upload_file"):
        # SDK mismatch — provide informative error so user can act
        msg = (
            "The installed google.generativeai SDK does not expose 'upload_file'. "
            "This code expects genai.upload_file(path=...). Upgrade google-generativeai "
            "to a version that supports file uploads, or adapt this function to your SDK."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    try:
        # create model handle
        try:
            # TODO: Verify your SDK offers GenerativeModel by this name.
            # Some SDK versions use different construction patterns.
            model = genai.GenerativeModel(MODEL_NAME)
        except Exception as e:
            logger.exception("Failed to instantiate GenerativeModel('%s'): %s", MODEL_NAME, e)
            raise RuntimeError(
                f"Could not instantiate model '{MODEL_NAME}'. "
                "Verify MODEL_NAME, your project access, and that the model exists in your GCP project/region."
            )

        # Optional safety: check file size before upload
        try:
            size_bytes = os.path.getsize(audio_path)
            max_bytes = 50 * 1024 * 1024  # example 50MB limit — adjust to your quota
            if size_bytes > max_bytes:
                logger.warning("Audio file is large (%.1f MB). Consider compressing before upload.", size_bytes / (1024 * 1024))
        except Exception:
            logger.debug("Could not determine audio file size prior to upload.")

        logger.info("Uploading audio to generative API: %s", audio_path)
        # upload_file should return a file reference acceptable to the SDK's generate_content call
        # TODO: confirm that genai.upload_file accepts path=... and returns the required ref for your SDK version
        audio_file_ref = genai.upload_file(path=audio_path)

        prompt = "You are a transcription assistant. Provide a clean, verbatim transcript of this audio. Do not summarize."

        logger.info("Requesting transcription from the model (timeout=%s seconds).", timeout_seconds)
        # TODO: verify generate_content signature in your SDK; adapt if necessary.
        response = model.generate_content(
            [prompt, audio_file_ref],
            request_options={"timeout": timeout_seconds},
        )

        # Extract text safely from response object (multiple possible shapes)
        if response and hasattr(response, "text") and response.text:
            transcript = response.text.strip()
            logger.info("Transcription returned (text attribute). length=%d", len(transcript))
            return transcript

        if response and hasattr(response, "candidates") and response.candidates:
            try:
                first = response.candidates[0]
                # try common shapes
                if hasattr(first, "content") and getattr(first.content, "parts", None):
                    parts = first.content.parts
                    transcript = "".join([getattr(p, "text", "") for p in parts]).strip()
                    logger.info("Transcription assembled from candidates.content.parts. length=%d", len(transcript))
                    return transcript
                elif hasattr(first, "output"):
                    transcript = str(first.output).strip()
                    logger.info("Transcription assembled from candidates[0].output. length=%d", len(transcript))
                    return transcript
            except Exception:
                logger.exception("Failed extracting transcript from response.candidates structure.")

        logger.error("Transcription failed: no text returned by model.")
        raise RuntimeError("Transcription failed: no text returned by model.")

    except Exception as e:
        logger.exception("Gemini transcription error: %s", e)
        raise RuntimeError(f"Gemini transcription failed: {e}")


def get_transcript_from_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Orchestrates download -> transcription -> cleanup.

    Returns:
      (transcript_text, None) on success
      (None, error_message) on failure
    """
    work_dir = tempfile.mkdtemp(prefix="yt_audio_")
    logger.info("Created temporary work directory: %s", work_dir)

    # Sanity check ffmpeg (warn only)
    _ensure_ffmpeg_available()

    try:
        audio_path = _download_audio_from_youtube(url, work_dir)
        transcript = _transcribe_audio_with_gemini(audio_path)
        return transcript, None
    except Exception as e:
        logger.error("Error in get_transcript_from_url: %s", e)
        logger.debug(traceback.format_exc())
        return None, str(e)
    finally:
        try:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir)
                logger.info("Cleaned up temporary work directory: %s", work_dir)
        except Exception:
            logger.exception("Failed to remove temporary work directory: %s", work_dir)
