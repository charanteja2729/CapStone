// frontend/src/components/ProfileMenu.js
import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import PropTypes from "prop-types";
import { getToken, getAuthHeaders, removeToken } from "../utils/auth";
import "./ProfileMenu.css";

const CHECK_INTERVAL_MS = 30 * 1000; // check every 30s

// helper: check if JWT token is expired (returns true if expired or invalid)
function isTokenExpired(token) {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return true;
    // base64url -> base64
    let payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    while (payload.length % 4) payload += "=";
    const decoded = atob(payload);
    const obj = JSON.parse(decoded);
    if (!obj.exp) return false; // no exp claim -> consider valid
    const now = Math.floor(Date.now() / 1000);
    return obj.exp <= now;
  } catch (err) {
    // invalid token format
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

  // sync incoming user prop (keeps component reactive when parent updates)
  useEffect(() => {
    setProfile(user || null);
  }, [user]);

  // close dropdown on outside click
  useEffect(() => {
    function onDocClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  // fetch profile from server (uses token header)
  async function fetchProfile() {
    const token = getToken();
    if (!token) {
      setProfile(null);
      return null;
    }
    try {
      setLoading(true);
      const res = await fetch(`${apiBase || ""}/api/me`, {
        method: "GET",
        headers: getAuthHeaders(), // expects Authorization header if token present
      });
      if (!res.ok) {
        // if unauthorized, treat as logged out
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
    } catch (e) {
      setErr("Network error while fetching profile");
      return null;
    } finally {
      setLoading(false);
    }
  }

  // logout helper that ensures token is removed and parent is notified
  function doLogout() {
    try {
      removeToken();
    } catch (e) {
      // ignore
    }
    setProfile(null);
    setOpen(false);
    if (typeof onLogout === "function") {
      try {
        onLogout();
      } catch (err) {
        // parent handler may navigate/remove state
      }
    }
    // ensure UI goes back to login route
    try {
      navigate("/", { replace: true });
    } catch (e) {
      // ignore navigation errors in some integration contexts
    }
  }

  // check token periodically and on focus, storage events
  useEffect(() => {
    function checkAndLogoutIfExpired() {
      const token = getToken();
      if (!token || isTokenExpired(token)) {
        // token missing or expired -> force logout
        doLogout();
      }
    }

    // check now on mount
    checkAndLogoutIfExpired();

    // interval check
    const id = setInterval(checkAndLogoutIfExpired, CHECK_INTERVAL_MS);

    // page visibility / focus
    const onFocus = () => checkAndLogoutIfExpired();
    window.addEventListener("focus", onFocus);
    window.addEventListener("visibilitychange", onFocus);

    // detect cross-tab token removal/changes
    const onStorage = (e) => {
      if (e.key === "token") {
        // if token removed in other tab or changed, validate now
        checkAndLogoutIfExpired();
      }
    };
    window.addEventListener("storage", onStorage);

    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("storage", onStorage);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // convenience display helpers
  const displayName = (profile && (profile.name || profile.email)) || "Guest";
  const displayPoints = (profile && (profile.points ?? 0)) || 0;
  const recentTopics = (profile && profile.recent_topics) || [];

  // UI render
  return (
    <div className="profile-menu" ref={menuRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          // refresh profile when opening to show latest points
          if (!open) fetchProfile();
        }}
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
          border: "1px solid rgba(0,0,0,0.08)",
          cursor: "pointer",
        }}
        title={displayName}
      >
        <div
          className="avatar"
          style={{
            width: 34,
            height: 34,
            borderRadius: 999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#2b6cb0",
            color: "white",
            fontWeight: 600,
          }}
        >
          {(displayName && displayName[0]?.toUpperCase()) || "U"}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 120 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{displayName}</span>
          <span style={{ fontSize: 12, color: "#666" }}>{displayPoints} pts</span>
        </div>
        <svg width="18" height="18" viewBox="0 0 24 24" style={{ marginLeft: 6 }}>
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
            boxShadow: "0 8px 24px rgba(0,0,0,0.08)",
            borderRadius: 8,
            padding: 12,
            zIndex: 1200,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div
              style={{
                width: 46,
                height: 46,
                borderRadius: 999,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "#2b6cb0",
                color: "white",
                fontWeight: 700,
                fontSize: 18,
              }}
            >
              {displayName[0]?.toUpperCase() || "U"}
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <strong style={{ fontSize: 14 }}>{displayName}</strong>
              <span style={{ fontSize: 13, color: "#555" }}>{profile && profile.email}</span>
            </div>
          </div>

          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, color: "#888", marginBottom: 6 }}>Points</div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{displayPoints}</div>
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: "#888", marginBottom: 6 }}>Recent topics</div>
            {recentTopics.length === 0 ? (
              <div style={{ fontSize: 13, color: "#666" }}>No recent topics</div>
            ) : (
              <ul style={{ paddingLeft: 16, margin: 0 }}>
                {recentTopics.slice(0, 5).map((t, idx) => (
                  <li key={idx} style={{ fontSize: 13, marginBottom: 6 }}>
                    <strong>{t.title}</strong>
                    <div style={{ fontSize: 11, color: "#888" }}>
                      {t.time ? new Date(t.time).toLocaleString() : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              type="button"
              onClick={() => {
                // refresh profile immediately
                fetchProfile();
              }}
              style={{
                flex: 1,
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid rgba(0,0,0,0.06)",
                background: "#fff",
                cursor: "pointer",
              }}
            >
              Refresh
            </button>

            <button
              type="button"
              onClick={() => {
                doLogout();
              }}
              style={{
                flex: 1,
                padding: "8px 10px",
                borderRadius: 8,
                border: "none",
                background: "#ef4444",
                color: "white",
                cursor: "pointer",
              }}
            >
              Logout
            </button>
          </div>

          {err && (
            <div style={{ marginTop: 10, color: "#b91c1c", fontSize: 13 }}>
              {err}
            </div>
          )}
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
