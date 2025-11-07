import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import Auth from './components/Auth';
import Summarizer from './components/Summarizer';
import VideoProcessor from './components/VideoProcessor';
import Quiz from './components/Quiz';
import Spinner from './components/Spinner';
import NavBar from './components/NavBar';
import MySummaries from './components/MySummaries';
import WeakAreas from './components/WeakAreas';

import './App.css';
import { getAuthHeaders, getToken, removeToken } from './utils/auth';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  const rafRef = useRef(null);
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
          if (res.status === 401 || res.status === 403) removeToken();
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
          path="/app/*"
          element={user ? (
            <AuthedApp
              user={user}
              setUser={setUser}
            />
          ) : (
            <Navigate to="/" replace />
          )}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

// ----------------------
// Protected Shell
// ----------------------
function AuthedApp({ user, setUser }) {
  const handleLogout = () => {
    removeToken();
    setUser(null);
  };

  return (
    <>
      <NavBar user={user} apiBase={API_BASE} onLogout={handleLogout} />
      <Routes>
        <Route path="/" element={<Dashboard user={user} setUser={setUser} />} />
        <Route path="/my-summaries" element={<MySummaries />} />
        <Route path="/weak-areas" element={<WeakAreas />} />
      </Routes>
    </>
  );
}

// ----------------------
// Dashboard
// ----------------------
function Dashboard({ user, setUser }) {
  const [directText, setDirectText] = useState('');
  const [generatedNotes, setGeneratedNotes] = useState('');
  const [isLoadingNotes, setIsLoadingNotes] = useState(false);

  const [quiz, setQuiz] = useState(null);
  const [isLoadingVideo, setIsLoadingVideo] = useState(false);
  const [isLoadingQuiz, setIsLoadingQuiz] = useState(false);
  const [error, setError] = useState('');

  const [lastTitle, setLastTitle] = useState('');
  const [cacheHit, setCacheHit] = useState(false);

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
        headers: getAuthHeaders(true),
        body: JSON.stringify({ text: directText }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to generate notes.');
      }

      const data = await res.json();
      setGeneratedNotes(data.notes || '');
      if (data.title) setLastTitle(data.title);

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

      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Something went wrong when generating the quiz.');
    } finally {
      setIsLoadingQuiz(false);
    }
  };

  const handleVideoProcessComplete = async (data) => {
    if (!data) return;

    if (data.notes) setGeneratedNotes(data.notes);
    if (data.quiz) setQuiz(data.quiz);
    if (data.transcript && !directText) setDirectText(data.transcript);

    if (data.title) setLastTitle(data.title);
    if (typeof data.cache_hit === 'boolean') setCacheHit(data.cache_hit);

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
      const res = await fetch(`${API_BASE}/api/submit-quiz`, {
        method: 'POST',
        headers: getAuthHeaders(true),
        body: JSON.stringify({ quiz: quizPayload, answers }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to submit quiz.');
      }

      const data = await res.json();
      alert(`Quiz submitted.\nScore: ${data.correct}/${data.total}\nPoints: ${data.points_awarded}`);

      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Error submitting quiz.');
    }
  };

  return (
    <div className="app-container">
      <div className="dashboard-header">
        <div>
          <h1>AI Study Tools</h1>
          <p>Generate notes & quizzes from text or video</p>
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
        setGeneratedNotes={setGeneratedNotes}
        isLoadingNotes={isLoadingNotes}
        generatedNotes={generatedNotes}
        isLoadingQuiz={isLoadingQuiz}
        handleGenerateQuiz={handleGenerateQuiz}
        lastTitle={lastTitle}
        cacheHit={cacheHit}
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
          <Quiz quizData={quiz} onSubmit={(answers) => handleSubmitQuiz(quiz, answers)} />
        </div>
      )}

      <div style={{ height: 60 }} />
    </div>
  );
}
