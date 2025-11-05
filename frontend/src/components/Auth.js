// frontend/src/components/Auth.js
import React, { useState, useRef, useEffect } from 'react';
import { removeToken } from '../utils/auth';
import './Auth.css';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

export default function Auth({ onLogin }) {
  const wrapperRef = useRef(null);
  const cardRef = useRef(null);

  const [isLoginMode, setIsLoginMode] = useState(true);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const resetForm = () => {
    setName('');
    setEmail('');
    setPassword('');
    setError('');
  };

  const switchMode = () => {
    setIsLoginMode(!isLoginMode);
    resetForm();
  };

  // ✅ Correct token saving key
  const saveToken = (token) => {
    try {
      localStorage.setItem('access_token', token);
    } catch (e) {
      console.warn('saveToken error:', e);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    setError('');
    setLoading(true);

    try {
      if (!email || !password) {
        throw new Error('Email and password are required.');
      }

      const endpoint = isLoginMode ? '/api/login' : '/api/register';
      const payload = isLoginMode
        ? { email, password }
        : { name, email, password };

      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data?.error || 'Authentication failed.');
      }

      if (isLoginMode) {
        const { access_token, user } = data;
        if (!access_token) throw new Error('No access token returned from server.');

        saveToken(access_token);

        // ✅ Notify parent (App.js) so redirect can happen
        if (typeof onLogin === 'function') {
          onLogin(user || { email });
        }
      } else {
        // ✅ Registration success — switch to login mode
        setIsLoginMode(true);
        setPassword('');
        setError('Registered successfully. Please log in.');
        if (data?.user?.email) setEmail(data.user.email);
      }
    } catch (err) {
      setError(err?.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    removeToken(); // removes access_token
    if (typeof onLogin === 'function') onLogin(null);
  };

  // ---------------------- Pointer animation UI logic (unchanged) ----------------------
  useEffect(() => {
    const wrapperEl = wrapperRef.current;
    const cardEl = cardRef.current;
    if (!wrapperEl || !cardEl) return;

    cardEl.style.setProperty('--mx', '50%');
    cardEl.style.setProperty('--my', '50%');

    const move = (e) => {
      const clientX = (e.touches?.[0]?.clientX) ?? e.clientX;
      const clientY = (e.touches?.[0]?.clientY) ?? e.clientY;
      if (clientX == null || clientY == null) return;

      const rect = cardEl.getBoundingClientRect();
      const xPct = ((clientX - rect.left) / rect.width) * 100;
      const yPct = ((clientY - rect.top) / rect.height) * 100;

      cardEl.style.setProperty('--mx', `${Math.max(0, Math.min(100, xPct))}%`);
      cardEl.style.setProperty('--my', `${Math.max(0, Math.min(100, yPct))}%`);
    };

    const reset = () => {
      cardEl.style.setProperty('--mx', '50%');
      cardEl.style.setProperty('--my', '50%');
    };

    wrapperEl.addEventListener('mousemove', move);
    wrapperEl.addEventListener('touchmove', move, { passive: true });
    wrapperEl.addEventListener('mouseleave', reset);
    wrapperEl.addEventListener('touchend', reset);

    // also track on the card itself
    cardEl.addEventListener('mousemove', move);
    cardEl.addEventListener('touchmove', move, { passive: true });
    cardEl.addEventListener('mouseleave', reset);
    cardEl.addEventListener('touchend', reset);

    return () => {
      wrapperEl.removeEventListener('mousemove', move);
      wrapperEl.removeEventListener('touchmove', move);
      wrapperEl.removeEventListener('mouseleave', reset);
      wrapperEl.removeEventListener('touchend', reset);

      cardEl.removeEventListener('mousemove', move);
      cardEl.removeEventListener('touchmove', move);
      cardEl.removeEventListener('mouseleave', reset);
      cardEl.removeEventListener('touchend', reset);
    };
  }, []);
  // ------------------------------------------------------------------

  return (
    <div ref={wrapperRef} className="auth-wrapper" aria-live="polite">
      <div className="auth-brand">
        <a href="/" className="auth-brand-link">Compresso</a>
      </div>
      <div ref={cardRef} className="auth-card" role="region" aria-label="Authentication">
        <h2>{isLoginMode ? 'Login' : 'Sign up'}</h2>
        <div className="title-accent" aria-hidden />

        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {!isLoginMode && (
            <div className="form-row">
              <label htmlFor="auth-name">Name</label>
              <input
                id="auth-name"
                type="text"
                placeholder="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}

          <div className="form-row">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              placeholder="your@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>

          <div className="form-row">
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isLoginMode ? 'current-password' : 'new-password'}
              required
            />
          </div>

          {error && <div className="auth-error">{error}</div>}

          <div className="form-actions">
            <button type="submit" className="primary-btn" disabled={loading}>
              {loading
                ? (isLoginMode ? 'Logging in...' : 'Signing up...')
                : (isLoginMode ? 'Login' : 'Create account')}
            </button>

            <button
              type="button"
              className="link-btn"
              onClick={switchMode}
              disabled={loading}
            >
              {isLoginMode ? "Don't have an account? Sign up" : 'Already have an account? Login'}
            </button>
          </div>
        </form>

        <div style={{ marginTop: 8 }}>
          <button className="secondary-btn" onClick={handleLogout} type="button">
            Logout (clear token)
          </button>
        </div>
      </div>
    </div>
  );
}
