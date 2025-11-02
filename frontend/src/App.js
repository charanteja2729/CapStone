// frontend/src/App.js
import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Summarizer from './components/Summarizer';
import VideoProcessor from './components/VideoProcessor';
import Quiz from './components/Quiz';
import Spinner from './components/Spinner';
import ProfileMenu from './components/ProfileMenu';
import Auth from './components/Auth';
import './App.css';

import { getAuthHeaders, getToken, removeToken } from './utils/auth';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  // ref used for requestAnimationFrame loop (throttling)
  const rafRef = useRef(null);
  // store latest pointer coords to be processed in RAF
  const pointerRef = useRef({ x: null, y: null });

  useEffect(() => {
    const attemptFetchProfile = async () => {
      const token = getToken();
      if (!token) {
        setAuthLoading(false);
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/api/me`, {
          method: 'GET',
          headers: getAuthHeaders(),
        });

        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            removeToken();
          }
          setAuthLoading(false);
          return;
        }

        const data = await res.json().catch(() => ({}));
        setUser(data.user || null);
      } catch (err) {
        console.warn('Could not fetch /api/me:', err);
      } finally {
        setAuthLoading(false);
      }
    };

    attemptFetchProfile();
  }, []);

  // ---------------------------
  // Interactive pointer wiring
  // ---------------------------
  useEffect(() => {
    // initialize root vars
    const root = document.documentElement;
    root.style.setProperty('--mx', '50%');
    root.style.setProperty('--my', '50%');

    // set pointer coords and schedule RAF update
    const scheduleUpdate = (clientX, clientY) => {
      pointerRef.current.x = clientX;
      pointerRef.current.y = clientY;

      if (rafRef.current != null) return; // already scheduled
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        const px = pointerRef.current.x;
        const py = pointerRef.current.y;
        if (px == null || py == null) return;

        const w = window.innerWidth || document.documentElement.clientWidth;
        const h = window.innerHeight || document.documentElement.clientHeight;

        // compute percentages and clamp 0..100
        const xPct = Math.max(0, Math.min(100, (px / w) * 100));
        const yPct = Math.max(0, Math.min(100, (py / h) * 100));

        root.style.setProperty('--mx', `${xPct}%`);
        root.style.setProperty('--my', `${yPct}%`);
      });
    };

    const handleMouseMove = (e) => {
      scheduleUpdate(e.clientX, e.clientY);
    };

    const handleTouchMove = (e) => {
      if (e.touches && e.touches[0]) {
        scheduleUpdate(e.touches[0].clientX, e.touches[0].clientY);
      }
    };

    const resetToCenter = () => {
      // cancel any waiting RAF
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      pointerRef.current.x = null;
      pointerRef.current.y = null;
      root.style.setProperty('--mx', '50%');
      root.style.setProperty('--my', '50%');
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('mouseleave', resetToCenter);
    window.addEventListener('touchend', resetToCenter);
    window.addEventListener('blur', resetToCenter);

    // cleanup
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('mouseleave', resetToCenter);
      window.removeEventListener('touchend', resetToCenter);
      window.removeEventListener('blur', resetToCenter);
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, []); // run once on mount

  if (authLoading) {
    return (
      <div className="centered">
        <Spinner text="Checking session..." />
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={user ? <Navigate to="/app" replace /> : <Auth onLogin={(u) => setUser(u)} />}
        />
        <Route
          path="/app"
          element={user ? <Dashboard user={user} setUser={setUser} /> : <Navigate to="/" replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

// -------------------------
// Dashboard: protected page after login
// -------------------------
function Dashboard({ user, setUser }) {
  const [directText, setDirectText] = useState('');
  const [generatedNotes, setGeneratedNotes] = useState('');
  const [isLoadingNotes, setIsLoadingNotes] = useState(false);

  const [quiz, setQuiz] = useState(null);
  const [isLoadingVideo, setIsLoadingVideo] = useState(false);
  const [isLoadingQuiz, setIsLoadingQuiz] = useState(false);
  const [error, setError] = useState('');

  const [videoUrl, setVideoUrl] = useState('');
  const [lastTitle, setLastTitle] = useState(''); // last processed title/topic

  // helper that refreshes the profile and updates the top-level user state
  const refreshProfile = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const meRes = await fetch(`${API_BASE}/api/me`, {
        method: 'GET',
        headers: getAuthHeaders(),
      });
      if (meRes.ok) {
        const payload = await meRes.json().catch(() => ({}));
        setUser(payload.user || null);
      }
    } catch (err) {
      console.warn('refreshProfile failed', err);
    }
  };

  const handleGenerateNotes = async (e) => {
    e && e.preventDefault && e.preventDefault();
    setIsLoadingNotes(true);
    setError('');
    setGeneratedNotes('');
    setQuiz(null);

    try {
      if (!directText) throw new Error('Please paste some text to summarize.');

      const res = await fetch(`${API_BASE}/api/summarize`, {
        method: 'POST',
        headers: getAuthHeaders(true), // ensure Content-Type and Authorization if available
        body: JSON.stringify({ text: directText }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to generate notes.');
      }

      const data = await res.json();
      setGeneratedNotes(data.notes || '');
      if (data.title) setLastTitle(data.title);

      // refresh profile so points/summarize_count/recent_topics show up
      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Something went wrong while generating notes.');
    } finally {
      setIsLoadingNotes(false);
    }
  };

  const handleGenerateQuiz = async () => {
    setIsLoadingQuiz(true);
    setError('');
    setQuiz(null);

    try {
      const textForQuiz = directText;
      if (!textForQuiz) throw new Error('Provide text to generate a quiz.');

      const res = await fetch(`${API_BASE}/api/generate-quiz`, {
        method: 'POST',
        headers: getAuthHeaders(true),
        body: JSON.stringify({ text: textForQuiz }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to generate quiz.');
      }

      const data = await res.json();
      if (data.quiz && data.quiz.length > 0) {
        setQuiz(data.quiz);
      } else {
        setError('Could not generate a quiz from the provided text.');
      }

      // refresh profile — generate-quiz increments points on server
      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Something went wrong when generating the quiz.');
    } finally {
      setIsLoadingQuiz(false);
    }
  };

  const handleVideoProcessComplete = async (data) => {
    if (!data) return;

    // --- ADD THIS LOGGING ---
    console.log("--- DEBUG: Data from /api/process-video ---");
    console.log("Received title:", data.title);
    if (data.quiz && data.quiz.length > 0) {
      console.log("Received quiz[0].topic:", data.quiz[0].topic);
    } else {
      console.log("No quiz data received.");
    }
    console.log("-------------------------------------------");
    // --- END OF LOGGING ---

    if (data.notes) setGeneratedNotes(data.notes);
    if (data.notes) setGeneratedNotes(data.notes);
    if (data.quiz) setQuiz(data.quiz);
    if (data.transcript && !directText) {
      setDirectText(data.transcript);
    }

    if (data.title) setLastTitle(data.title);
    if (data.topic) setLastTitle(data.topic);

    // server increments points on process-video; refresh profile if logged in
    await refreshProfile();
  };

  const handleSubmitQuiz = async (quizPayload, answers) => {
    setError('');
    if (!quizPayload || !answers || quizPayload.length !== answers.length) {
      setError('Invalid quiz submission.');
      return;
    }

    if (!getToken()) {
      setError('Please login to submit quiz results and earn points.');
      return;
    }

    try {
      const topicToSend =
        // This is the new, correct logic
        (Array.isArray(quizPayload) && quizPayload.length > 0 ? quizPayload[0].topic : null) || // <-- 1. Prioritize the topic from the quiz
        lastTitle || // <-- 2. Fallback to the video title
        '';

      const res = await fetch(`${API_BASE}/api/submit-quiz`, {
        method: 'POST',
        headers: getAuthHeaders(true),
        body: JSON.stringify({ quiz: quizPayload, answers, topic: topicToSend }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to submit quiz.');
      }

      const data = await res.json();
      alert(`Quiz submitted. Score: ${data.correct}/${data.total}. Points awarded: ${data.points_awarded}`);

      // refresh profile
      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Error submitting quiz.');
    }
  };

  const handleLogout = () => {
    removeToken();
    setUser(null);
    // route back to auth page will happen automatically because route guards redirect
  };

  return (
    <div className="app-container">
      <div className="dashboard-header">
        <div>
          <h1>AI Study Tools</h1>
          <p>Generate notes & quizzes from text or video</p>
        </div>

        <div style={{ marginLeft: 'auto' }}>
          <ProfileMenu
            user={user}
            apiBase={API_BASE}
            onLogout={() => {
              removeToken();
              setUser(null);
            }}
          />
        </div>
      </div>

      <VideoProcessor
        onProcessComplete={handleVideoProcessComplete}
        isLoading={isLoadingVideo}
        onSetLoading={(v) => setIsLoadingVideo(v)}
        onError={setError}
      />

      <hr />

      <Summarizer
        directText={directText}
        setDirectText={setDirectText}
        handleGenerateNotes={handleGenerateNotes}
        isLoadingNotes={isLoadingNotes}
        generatedNotes={generatedNotes}
        isLoadingQuiz={isLoadingQuiz}
        handleGenerateQuiz={handleGenerateQuiz}
      />

      {error && (
        <div className="error-message">
          <p className="error-title">Error</p>
          <p>{error}</p>
        </div>
      )}

      {isLoadingQuiz && <Spinner text="Building your quiz..." />}
      {isLoadingVideo && <Spinner text="Processing video and generating notes/quiz..." />}

      {quiz && !isLoadingQuiz && !isLoadingVideo && (
        <div className="quiz-section">
          <Quiz
            quizData={quiz}
            onSubmit={(answers) => handleSubmitQuiz(quiz, answers)}
          />
        </div>
      )}

      <div style={{ height: 60 }} /> {/* small bottom spacer */}
    </div>
  );
}
