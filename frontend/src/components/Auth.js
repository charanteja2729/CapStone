// frontend/src/components/Auth.js
import React, { useState } from 'react';
import { saveToken, removeToken } from '../utils/auth';

export default function Auth({ onLogin }) {
  // onLogin is an optional callback: (user) => setUser(...) in parent
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

  const handleSubmit = async (e) => {
    e.preventDefault();
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

      const res = await fetch('http://localhost:5000' + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        // backend returns { error: '...' }
        throw new Error(data.error || 'Authentication failed');
      }

      // For login: backend returns { access_token, user: { email, name } }
      // For register: backend returns { message, user: { email, name } }
      if (isLoginMode) {
        const { access_token, user } = data;
        if (!access_token) {
          throw new Error('No access token returned from server.');
        }
        // Save token
        saveToken(access_token);

        // Inform parent
        if (typeof onLogin === 'function') {
          onLogin(user || { email });
        }
      } else {
        // on successful registration, flip to login mode (or auto-login if you prefer)
        // Here we auto-switch to login mode and pre-fill email
        setIsLoginMode(true);
        setPassword('');
        setError('Registered successfully. Please log in.');
      }
    } catch (err) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    removeToken();
    if (typeof onLogin === 'function') onLogin(null);
  };

  return (
    <div className="auth-card">
      <h2>{isLoginMode ? 'Login' : 'Sign up'}</h2>

      <form onSubmit={handleSubmit} className="auth-form">
        {!isLoginMode && (
          <div className="form-row">
            <label>Name</label>
            <input
              type="text"
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        )}

        <div className="form-row">
          <label>Email</label>
          <input
            type="email"
            placeholder="your@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="form-row">
          <label>Password</label>
          <input
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && <div className="auth-error">{error}</div>}

        <div className="form-actions">
          <button type="submit" className="primary-btn" disabled={loading}>
            {loading ? (isLoginMode ? 'Logging in...' : 'Signing up...') : (isLoginMode ? 'Login' : 'Create account')}
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
        <button className="secondary-btn" onClick={handleLogout}>
          Logout (clear token)
        </button>
      </div>
    </div>
  );
}
