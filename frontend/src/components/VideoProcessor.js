// frontend/src/components/VideoProcessor.js

import React, { useState } from 'react';
import Spinner from './Spinner';
import styles from './VideoProcessor.module.css';

const isProbablyUrl = (value) => {
  try {
    const u = new URL(value);
    return !!u.protocol && (u.protocol === 'http:' || u.protocol === 'https:');
  } catch {
    return false;
  }
};

const VideoProcessor = ({ onProcessComplete, isLoading, onSetLoading, onError }) => {
  const [videoUrl, setVideoUrl] = useState('');

  const safeParseJson = async (res) => {
    try {
      return await res.json();
    } catch {
      return null;
    }
  };

  const handleProcessVideo = async (e) => {
    e.preventDefault();

    // local validation before showing spinner
    const raw = (videoUrl || '').trim();
    onError && onError(''); // clear previous error
    if (!raw) {
      onError && onError('Please paste a YouTube URL.');
      return;
    }
    if (!isProbablyUrl(raw)) {
      onError && onError('Please enter a valid URL (must start with http:// or https://).');
      return;
    }
    // optional: further restrict to YouTube domains
    // const allowed = ['www.youtube.com', 'youtube.com', 'youtu.be'];
    // if (!allowed.includes(new URL(raw).hostname.replace('m.', ''))) { ... }

    onSetLoading && onSetLoading(true);

    try {
      const res = await fetch('http://localhost:5000/api/process-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // include credentials if your backend relies on cookies:
        // credentials: 'include',
        body: JSON.stringify({ video_url: raw }),
      });

      // Try to parse JSON safely (server might return non-JSON on error)
      const parsed = await safeParseJson(res);

      if (!res.ok) {
        const errMsg = parsed && parsed.error ? parsed.error : `Failed to process video (status ${res.status})`;
        throw new Error(errMsg);
      }

      // If server responded with empty body or non-JSON, handle gracefully
      if (!parsed) {
        throw new Error('Server returned an unexpected response.');
      }

      onProcessComplete && onProcessComplete(parsed);
    } catch (err) {
      // err.message is user-facing; you might want to map it to friendlier text here
      onError && onError(err.message || 'Failed to process video.');
    } finally {
      onSetLoading && onSetLoading(false);
    }
  };

  return (
    <form onSubmit={handleProcessVideo} className={styles.formContainer}>
      <div className={styles.inputGroup}>
        <label htmlFor="video_url">YouTube Video URL</label>
        <input
          id="video_url"
          className={styles.input}
          type="text"
          value={videoUrl}
          onChange={(e) => setVideoUrl(e.target.value)}
          placeholder="e.g., https://www.youtube.com/watch?v=..."
          aria-label="YouTube Video URL"
        />
      </div>

      <button
        type="submit"
        disabled={isLoading}
        aria-busy={isLoading}
        className={styles.processButton}
      >
        {isLoading ? (
          <>
            <Spinner /> Processing Video...
          </>
        ) : (
          'Process Video'
        )}
      </button>
    </form>
  );
};

export default VideoProcessor;
