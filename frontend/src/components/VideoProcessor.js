// src/components/VideoProcessor.js
import React, { useState, useRef, useEffect } from 'react';
import Spinner from './Spinner';
import styles from './VideoProcessor.module.css';
import { getAuthHeaders } from '../utils/auth';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

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
  authToken,
  includeCredentials = false,
}) => {
  const [videoUrl, setVideoUrl] = useState('');
  const controllerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (controllerRef.current) controllerRef.current.abort();
    };
  }, []);

  const safeParseJson = async (res) => {
    const ct = res.headers.get('content-type') || '';
    if (res.status === 204) return null;
    if (!ct.includes('application/json')) {
      try { return await res.json(); } catch { return null; }
    }
    try { return await res.json(); } catch { return null; }
  };

  const handleProcessVideo = async (e) => {
    e.preventDefault();
    const raw = (videoUrl || '').trim();
    onError && onError('');

    if (!raw) return onError && onError('Please paste a YouTube URL.');
    if (!isProbablyUrl(raw)) return onError && onError('Please enter a valid URL (must start with http:// or https://).');

    const token = authToken || localStorage.getItem('access_token');

    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    onSetLoading && onSetLoading(true);

    try {
      const opts = {
        method: 'POST',
        headers: getAuthHeaders(true),
        body: JSON.stringify({ video_url: raw }),
        signal: controller.signal,
      };
      if (includeCredentials) opts.credentials = 'include';

      const res = await fetch(`${API_BASE}/api/process-video`, opts);
      const parsed = await safeParseJson(res);

      if (!res.ok) {
        const errMsg = parsed?.error ? parsed.error : `Failed to process video (status ${res.status})`;
        throw new Error(errMsg);
      }
      if (!parsed) throw new Error('Server returned an unexpected response.');

      onProcessComplete && onProcessComplete(parsed);
    } catch (err) {
      if (err.name === 'AbortError') onError && onError('Request cancelled.');
      else onError && onError(err.message || 'Failed to process video.');
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

      <button type="submit" disabled={isLoading} aria-busy={isLoading} className={styles.processButton}>
        {isLoading ? (<><Spinner /> Processing Video...</>) : ('Process Video')}
      </button>
    </form>
  );
};

export default VideoProcessor;
