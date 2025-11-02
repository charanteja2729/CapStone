// frontend/src/components/VideoProcessor.js

import React, { useState, useRef, useEffect } from 'react';
import Spinner from './Spinner';
import styles from './VideoProcessor.module.css';
import { getAuthHeaders } from '../utils/auth';

const isProbablyUrl = (value) => {
  try {
    const u = new URL(value);
    return !!u.protocol && (u.protocol === 'http:' || u.protocol === 'https:');
  } catch {
    return false;
  }
};

const VideoProcessor = ({
  onProcessComplete,
  isLoading,
  onSetLoading,
  onError,
  authToken,            // optional: pass token as prop
  includeCredentials = false, // optional: set to true if using cookie auth
}) => {
  const [videoUrl, setVideoUrl] = useState('');
  const controllerRef = useRef(null);

  // Abort any in-flight request when component unmounts
  useEffect(() => {
    return () => {
      if (controllerRef.current) {
        controllerRef.current.abort();
      }
    };
  }, []);

  const safeParseJson = async (res) => {
    // If no content or content-length is zero, return null
    const ct = res.headers.get('content-type') || '';
    if (res.status === 204) return null;
    if (!ct.includes('application/json')) {
      // still try parsing if server lied about content-type
      try {
        return await res.json();
      } catch {
        return null;
      }
    }
    try {
      return await res.json();
    } catch {
      return null;
    }
  };

  const handleProcessVideo = async (e) => {
    e.preventDefault();

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

    // Prepare auth header (prop wins, fall back to localStorage)
    const token = authToken || localStorage.getItem('access_token');

    // Abort previous request if still running
    if (controllerRef.current) {
      controllerRef.current.abort();
    }
    const controller = new AbortController();
    controllerRef.current = controller;

    onSetLoading && onSetLoading(true);

    try {
      const opts = {
        method: 'POST',
        headers: getAuthHeaders(true), // <-- This automatically adds Content-Type and Authorization
        body: JSON.stringify({ video_url: raw }),
        signal: controller.signal,
      };
      if (includeCredentials) {
        opts.credentials = 'include';
      }

      const res = await fetch('http://localhost:5000/api/process-video', opts);

      const parsed = await safeParseJson(res);

      if (!res.ok) {
        const errMsg = parsed && parsed.error ? parsed.error : `Failed to process video (status ${res.status})`;
        throw new Error(errMsg);
      }

      if (!parsed) {
        throw new Error('Server returned an unexpected response.');
      }

      onProcessComplete && onProcessComplete(parsed);
    } catch (err) {
      if (err.name === 'AbortError') {
        // optional: ignore or surface a cancel message
        onError && onError('Request cancelled.');
      } else {
        onError && onError(err.message || 'Failed to process video.');
      }
    } finally {
      onSetLoading && onSetLoading(false);
      controllerRef.current = null;
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
