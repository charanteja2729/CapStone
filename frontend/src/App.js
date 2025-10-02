// frontend/src/App.js
import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import Summarizer from './components/Summarizer';
import VideoProcessor from './components/VideoProcessor';
import Quiz from './components/Quiz';
import Spinner from './components/Spinner';
import ProfileMenu from './components/ProfileMenu';
import './App.css';

import { getAuthHeaders, getToken, removeToken } from './utils/auth';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

// -------------------------
// AuthPage: Signup (left) + Login (right)
// -------------------------
function AuthPage({ onLogin }) {
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [signupName, setSignupName] = useState('');
  const [signupEmail, setSignupEmail] = useState('');
  const [signupPassword, setSignupPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const saveToken = (token) => {
    try {
      localStorage.setItem('token', token);
    } catch (e) {
      console.warn('Could not save token', e);
    }
  };

  const doLogin = async (email, password) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || 'Login failed');
      }
      const data = await res.json();
      const token = data.access_token;
      if (!token) throw new Error('No token returned');
      saveToken(token);

      // fetch profile using token directly (avoid depending on getAuthHeaders reading localStorage timing)
      try {
        const meRes = await fetch(`${API_BASE}/api/me`, {
          method: 'GET',
          headers: { Authorization: `Bearer ${token}` }
        });
        if (meRes.ok) {
          const meData = await meRes.json();
          onLogin(meData.user || { email });
        } else {
          onLogin({ email });
        }
      } catch (err) {
        onLogin({ email });
      }

      navigate('/app');
    } catch (err) {
      setError(err.message || 'Login error');
    } finally {
      setLoading(false);
    }
  };

  const handleLoginSubmit = (e) => {
    e.preventDefault();
    if (!loginEmail || !loginPassword) return setError('Provide email and password');
    doLogin(loginEmail.trim().toLowerCase(), loginPassword);
  };

  const handleSignupSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      if (!signupEmail || !signupPassword) throw new Error('Provide email and password for signup');
      const payload = { email: signupEmail.trim().toLowerCase(), password: signupPassword, name: signupName };
      const res = await fetch(`${API_BASE}/api/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || 'Signup failed');
      }

      // auto-login after signup
      await doLogin(payload.email, payload.password);

    } catch (err) {
      setError(err.message || 'Signup error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-column auth-signup">
          <h2>Create account</h2>
          <form onSubmit={handleSignupSubmit}>
            <label>Name (optional)</label>
            <input value={signupName} onChange={(e) => setSignupName(e.target.value)} />
            <label>Email</label>
            <input value={signupEmail} onChange={(e) => setSignupEmail(e.target.value)} />
            <label>Password</label>
            <input type="password" value={signupPassword} onChange={(e) => setSignupPassword(e.target.value)} />
            <button className="primary-btn" type="submit" disabled={loading}>Sign up</button>
          </form>
        </div>

        <div className="auth-column auth-login">
          <h2>Welcome back</h2>
          <form onSubmit={handleLoginSubmit}>
            <label>Email</label>
            <input value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} />
            <label>Password</label>
            <input type="password" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} />
            <button className="primary-btn" type="submit" disabled={loading}>Log in</button>
          </form>
        </div>
      </div>

      {loading && <div style={{ marginTop: 12 }}><Spinner text="Processing..." /></div>}
      {error && <div className="error-message" style={{ marginTop: 12 }}>{error}</div>}
    </div>
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

  const navigate = useNavigate();

  // helper that refreshes the profile and updates the top-level user state
  const refreshProfile = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const meRes = await fetch(`${API_BASE}/api/me`, { method: 'GET', headers: { Authorization: `Bearer ${token}` } });
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
        headers: getAuthHeaders(true), // ensure Content-Type and Authorization
        body: JSON.stringify({ text: directText }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to generate notes.');
      }

      const data = await res.json();
      setGeneratedNotes(data.notes || '');

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
        headers: getAuthHeaders(true), // ensure Content-Type & Authorization
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
    if (data.notes) setGeneratedNotes(data.notes);
    if (data.quiz) setQuiz(data.quiz);
    if (data.transcript && !directText) {
      setDirectText(data.transcript);
    }

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
      const res = await fetch(`${API_BASE}/api/submit-quiz`, {
        method: 'POST',
        headers: getAuthHeaders(true), // ensure Content-Type and Authorization
        body: JSON.stringify({ quiz: quizPayload, answers }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to submit quiz.');
      }

      const data = await res.json();
      alert(`Quiz submitted. Score: ${data.correct}/${data.total}. Points awarded: ${data.points_awarded}`);

      // refresh profile (you already had this, keep it)
      await refreshProfile();
    } catch (err) {
      setError(err.message || 'Error submitting quiz.');
    }
  };

  const handleLogout = () => {
    removeToken();
    setUser(null);
    navigate('/');
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
              navigate('/');
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
    </div>
  );
}

// -------------------------
// App: router & top level state
// -------------------------
export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

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

        const data = await res.json();
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
    return <div className="centered"><Spinner text="Checking session..." /></div>;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={user ? <Navigate to="/app" replace /> : <AuthPage onLogin={(u) => setUser(u)} />} />
        <Route path="/app" element={user ? <Dashboard user={user} setUser={setUser} /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
