// frontend/src/components/Auth.js
import React, { useState, useRef, useEffect } from 'react';
import { removeToken } from '../utils/auth';
import './Auth.css';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

export default function Auth({ onLogin }) {
  const wrapperRef = useRef(null); // listen here
  const cardRef = useRef(null);    // compute positions relative to this

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

  // local helper to save token
  const saveToken = (token) => {
    try {
      localStorage.setItem('token', token);
    } catch (e) {
      console.warn('saveToken error', e);
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

      let data = {};
      try {
        data = await res.json();
      } catch (jsonErr) {
        if (!res.ok) throw new Error('Authentication failed');
      }

      if (!res.ok) {
        throw new Error(data?.error || 'Authentication failed');
      }

      if (isLoginMode) {
        const { access_token, user } = data;
        if (!access_token) throw new Error('No access token returned from server.');
        saveToken(access_token);
        if (typeof onLogin === 'function') onLogin(user || { email });
      } else {
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
    removeToken();
    if (typeof onLogin === 'function') onLogin(null);
  };

  // Pointer handling:
  // - listen on wrapperRef so movement anywhere in the wrapper triggers
  // - compute percentages relative to the cardRef (so gradient positions are correct)
  useEffect(() => {
    const wrapperEl = wrapperRef.current;
    const cardEl = cardRef.current;
    if (!wrapperEl || !cardEl) return;

    // initialize
    cardEl.style.setProperty('--mx', '50%');
    cardEl.style.setProperty('--my', '50%');

    const handleMove = (e) => {
      const clientX = (e.touches && e.touches[0]) ? e.touches[0].clientX : e.clientX;
      const clientY = (e.touches && e.touches[0]) ? e.touches[0].clientY : e.clientY;
      if (clientX == null || clientY == null) return;

      const rect = cardEl.getBoundingClientRect();
      // compute percent relative to the card
      const xPct = ((clientX - rect.left) / rect.width) * 100;
      const yPct = ((clientY - rect.top) / rect.height) * 100;

      cardEl.style.setProperty('--mx', `${Math.max(0, Math.min(100, xPct))}%`);
      cardEl.style.setProperty('--my', `${Math.max(0, Math.min(100, yPct))}%`);
    };

    const reset = () => {
      cardEl.style.setProperty('--mx', '50%');
      cardEl.style.setProperty('--my', '50%');
    };

    wrapperEl.addEventListener('mousemove', handleMove);
    wrapperEl.addEventListener('touchmove', handleMove, { passive: true });
    wrapperEl.addEventListener('mouseleave', reset);
    wrapperEl.addEventListener('touchend', reset);

    // Also keep card's own pointer events (optional) so card still responds if user hovers directly
    cardEl.addEventListener('mousemove', handleMove);
    cardEl.addEventListener('touchmove', handleMove, { passive: true });
    cardEl.addEventListener('mouseleave', reset);
    cardEl.addEventListener('touchend', reset);

    return () => {
      wrapperEl.removeEventListener('mousemove', handleMove);
      wrapperEl.removeEventListener('touchmove', handleMove);
      wrapperEl.removeEventListener('mouseleave', reset);
      wrapperEl.removeEventListener('touchend', reset);

      cardEl.removeEventListener('mousemove', handleMove);
      cardEl.removeEventListener('touchmove', handleMove);
      cardEl.removeEventListener('mouseleave', reset);
      cardEl.removeEventListener('touchend', reset);
    };
  }, []);

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
                name="name"
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
              name="email"
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
              name="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isLoginMode ? 'current-password' : 'new-password'}
              required
            />
          </div>

          {error && (
            <div className="auth-error" role="status" aria-live="polite">
              {error}
            </div>
          )}

          <div className="form-actions">
            <button
              type="submit"
              className="primary-btn"
              disabled={loading}
              aria-disabled={loading}
            >
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
          <button
            className="secondary-btn"
            onClick={handleLogout}
            type="button"
            title="Clear saved auth token"
          >
            Logout (clear token)
          </button>
        </div>
      </div>
    </div>
  );
}
