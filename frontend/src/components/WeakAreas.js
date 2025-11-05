import React, { useEffect, useState } from 'react';
import { getAuthHeaders } from '../utils/auth';
import ReactMarkdown from 'react-markdown';

const API_BASE = process.env.REACT_APP_API_BASE || 'http://localhost:5000';

// ✅ Convert array → markdown bullets
const formatExplanation = (exp) => {
  if (Array.isArray(exp)) {
    return exp.map(line => `- ${line}`).join("\n");
  }
  return typeof exp === "string" ? exp : "";
};

export default function WeakAreas() {
  const [topics, setTopics] = useState([]);
  const [explanations, setExplanations] = useState({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = async () => {
    setLoading(true);
    setErr('');
    try {
      const res = await fetch(`${API_BASE}/api/explain-weak-areas`, {
        headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `Failed (${res.status})`);
      setTopics(data.topics || []);
      setExplanations(data.explanations || {});
    } catch (e) {
      setErr(e.message || 'Failed to fetch weak areas');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div style={{ padding: 16 }}>Loading…</div>;
  if (err) return <div style={{ padding: 16, color: '#b91c1c' }}>{err}</div>;
  if (!topics.length) return <div style={{ padding: 16 }}>No weak areas found yet. Take a quiz first.</div>;

  return (
    <div style={{ maxWidth: 900, margin: '16px auto', padding: 12 }}>
      <h2>Weak Areas</h2>
      <p style={{ color: '#666' }}>Based on your last 10 mistakes.</p>

      {topics.map((t) => (
        <div key={t} style={{ margin: '16px 0', padding: 12, border: '1px solid rgba(0,0,0,0.06)', borderRadius: 8 }}>
          <h3 style={{ marginTop: 0 }}>{t}</h3>
          <div>
            <ReactMarkdown>
              {formatExplanation(explanations?.[t]) || '_No explanation yet._'}
            </ReactMarkdown>
          </div>
        </div>
      ))}

      <div style={{ marginTop: 16 }}>
        <button
          onClick={load}
          style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(0,0,0,0.08)', background: '#fff', cursor: 'pointer' }}
        >
          Refresh
        </button>
      </div>
    </div>
  );
}
