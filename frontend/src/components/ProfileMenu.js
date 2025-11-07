// src/components/ProfileMenu.js
import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import PropTypes from "prop-types";
import { getToken, getAuthHeaders, removeToken } from "../utils/auth";
import "./ProfileMenu.css";

const CHECK_INTERVAL_MS = 30 * 1000;

function isTokenExpired(token) {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return true;
    let payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    while (payload.length % 4) payload += "=";
    const decoded = atob(payload);
    const obj = JSON.parse(decoded);
    if (!obj.exp) return false;
    const now = Math.floor(Date.now() / 1000);
    return obj.exp <= now;
  } catch {
    return true;
  }
}

export default function ProfileMenu({ user, apiBase = "", onLogout }) {
  const [open, setOpen] = useState(false);
  const [profile, setProfile] = useState(user || null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const menuRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => { setProfile(user || null); }, [user]);

  useEffect(() => {
    function onDocClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  async function fetchProfile() {
    const token = getToken();
    if (!token) { setProfile(null); return null; }
    try {
      setLoading(true);
      const res = await fetch(`${apiBase || ""}/api/me`, {
        method: "GET",
        headers: getAuthHeaders(),
      });
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          doLogout();
          return null;
        }
        const d = await res.json().catch(() => ({}));
        setErr(d.error || `Could not fetch profile (${res.status})`);
        return null;
      }
      const data = await res.json().catch(() => ({}));
      setProfile(data.user || null);
      return data.user || null;
    } catch {
      setErr("Network error while fetching profile");
      return null;
    } finally {
      setLoading(false);
    }
  }

  function doLogout() {
    try { removeToken(); } catch {}
    setProfile(null);
    setOpen(false);
    if (typeof onLogout === "function") {
      try { onLogout(); } catch {}
    }
    navigate("/login", { replace: true });
  }

  useEffect(() => {
    function checkAndLogoutIfExpired() {
      const token = getToken();
      if (!token || isTokenExpired(token)) doLogout();
    }
    checkAndLogoutIfExpired();
    const id = setInterval(checkAndLogoutIfExpired, CHECK_INTERVAL_MS);
    const onFocus = () => checkAndLogoutIfExpired();
    window.addEventListener("focus", onFocus);
    window.addEventListener("visibilitychange", onFocus);
    const onStorage = (e) => { if (e.key === "token") checkAndLogoutIfExpired(); };
    window.addEventListener("storage", onStorage);

    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const displayEmail = (profile && profile.email) || "guest@example.com";
  const displayInitial = displayEmail[0]?.toUpperCase() || "U";
  const displayPoints = (profile && (profile.points ?? 0)) || 0;
  const recentTopics = (profile && profile.recent_topics) || [];

  return (
    <div className="profile-menu" ref={menuRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => { setOpen(v => !v); if (!open) fetchProfile(); }}
        aria-haspopup="true"
        aria-expanded={open}
        className="profile-button"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          borderRadius: 8,
          background: "transparent",
          border: "1px solid rgba(255,255,255,0.06)",
          cursor: "pointer",
          color: "white"
        }}
      >
        <div className="avatar" style={{
          width: 32, height: 32, borderRadius: 999, display: "flex", alignItems: "center",
          justifyContent: "center", background: "#2b6cb0", color: "white", fontWeight: 600, fontSize: 14
        }}>
          {displayInitial}
        </div>
        <svg width="16" height="16" viewBox="0 0 24 24">
          <path d="M7 10l5 5 5-5H7z" fill="currentColor" />
        </svg>
      </button>

      {open && (
        <div
          className="profile-dropdown"
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 8px)",
            minWidth: 260,
            background: "white",
            borderRadius: 10,
            padding: 12,
            boxShadow: "0 10px 30px rgba(2,6,23,0.18)",
            zIndex: 1200
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{
              width: 42, height: 42, borderRadius: 999, display: "flex",
              alignItems: "center", justifyContent: "center",
              background: "#2b6cb0", color: "white", fontWeight: 700, fontSize: 18
            }}>
              {displayInitial}
            </div>
            <div>
              <strong style={{ fontSize: 14 }}>{displayEmail}</strong>
            </div>
          </div>

          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>Points</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{displayPoints}</div>
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: "#666", marginBottom: 6 }}>Recent topics</div>
            {recentTopics.length === 0 ? (
              <div style={{ fontSize: 13, color: "#666" }}>No recent topics</div>
            ) : (
              <ul style={{ paddingLeft: 16, margin: 0 }}>
                {recentTopics.slice(0, 5).map((t, idx) => (
                  <li key={idx} style={{ fontSize: 13, marginBottom: 6 }}>
                    <strong>{t.title}</strong>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              type="button"
              onClick={() => fetchProfile()}
              style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: "1px solid rgba(0,0,0,0.06)", background: "#fff", cursor: "pointer" }}
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => doLogout()}
              style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: "none", background: "#ef4444", color: "white", cursor: "pointer" }}
            >
              Logout
            </button>
          </div>

          {err && <div style={{ marginTop: 10, color: "#b91c1c", fontSize: 13 }}>{err}</div>}
        </div>
      )}
    </div>
  );
}

ProfileMenu.propTypes = {
  user: PropTypes.object,
  apiBase: PropTypes.string,
  onLogout: PropTypes.func,
};
