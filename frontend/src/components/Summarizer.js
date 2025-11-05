import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import Spinner from "./Spinner";
import styles from "./Summarizer.module.css";
import { getAuthHeaders } from "../utils/auth";

const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:5000";
const YT_REGEX =
  /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{11})/;

export default function Summarizer({
  directText,
  setDirectText,
  setGeneratedNotes,
  handleGenerateNotes,
  isLoadingNotes,
  generatedNotes,
  isLoadingQuiz,
  handleGenerateQuiz,
  lastTitle, // ✅ NEW
  cacheHit,  // ✅ NEW
}) {
  const [error, setError] = useState("");
  const [isVideoLoading, setIsVideoLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    const text = directText.trim();
    if (!text) {
      setError("Please paste text or a YouTube URL first.");
      return;
    }

    const ytMatch = text.match(YT_REGEX);

    // ✅ Normal text mode → use original handler
    if (!ytMatch) return handleGenerateNotes(e);

    // ✅ YouTube video mode
    setIsVideoLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/process-video`, {
        method: "POST",
        headers: getAuthHeaders(true),
        body: JSON.stringify({ video_url: text }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || "Failed to process video.");

      // ✅ Always show notes
      if (data.notes) setGeneratedNotes(data.notes);

      // ✅ Only set transcript when not from cache
      if (!data.cache_hit && data.transcript) {
        setDirectText(data.transcript);
      }
    } catch (err) {
      setError(err.message || "Error while processing video.");
    } finally {
      setIsVideoLoading(false);
    }
  };

  return (
    <>
      <form onSubmit={handleSubmit} className={styles.formContainer}>
        <div className={styles.textareaGroup}>
          <label htmlFor="direct_text">Text or YouTube URL</label>
          <textarea
            id="direct_text"
            className={styles.textarea}
            rows="10"
            value={directText}
            onChange={(e) => setDirectText(e.target.value)}
            placeholder="Paste text or a YouTube link here..."
          ></textarea>
        </div>

        <button
          type="submit"
          disabled={isLoadingNotes || isVideoLoading}
          className={styles.generateButton}
        >
          {isVideoLoading
            ? "Processing video..."
            : isLoadingNotes
            ? "Generating notes..."
            : "Generate Notes"}
        </button>
      </form>

      {(isVideoLoading || isLoadingNotes) && <Spinner text="Please wait..." />}

      {error && (
        <div className={styles.errorBox}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {generatedNotes && !isLoadingNotes && !isVideoLoading && (
        <div className={styles.notesSection}>
          <h2>Generated Notes</h2>

          {/* ✅ Show title + cache badge */}
          {lastTitle && (
            <p className={styles.noteTitle}>
              <strong>{lastTitle}</strong>{" "}
              {cacheHit ? (
                <span className={styles.cacheTag}>✅ Loaded from cache</span>
              ) : (
                <span className={styles.newTag}>✨ New summary</span>
              )}
            </p>
          )}

          <div className={styles.prose}>
            <ReactMarkdown>{generatedNotes}</ReactMarkdown>
          </div>

          <div className={styles.quizButtonContainer}>
            <button
              onClick={handleGenerateQuiz}
              disabled={isLoadingQuiz}
              className={styles.quizButton}
            >
              {isLoadingQuiz ? "Generating Quiz..." : "Generate Quiz"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
