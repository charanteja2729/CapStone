import React, { useEffect, useState } from "react";
import { getAuthHeaders } from "../utils/auth";
import ReactMarkdown from "react-markdown";

const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:5000";

export default function MySummaries() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  const [activeDetail, setActiveDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [err, setErr] = useState("");

  const fetchSummaries = async () => {
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(`${API_BASE}/api/my-summaries`, {
        headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load saved summaries");
      const list = data.saved_summaries || [];
      setItems(list);
      if (list[0]) setActive(list[0]);
    } catch (e) {
      setErr(e.message || "Failed to load saved summaries");
    } finally {
      setLoading(false);
    }
  };

  const fetchDetail = async (detailId) => {
    if (!detailId) {
      setActiveDetail(null);
      return;
    }
    setDetailLoading(true);
    setErr("");
    try {
      const res = await fetch(`${API_BASE}/api/my-summaries/${detailId}`, {
        headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load summary detail");
      setActiveDetail(data);
    } catch (e) {
      setErr(e.message || "Failed to load summary detail");
      setActiveDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    fetchSummaries();
  }, []);

  useEffect(() => {
    const handler = () => fetchSummaries();
    window.addEventListener("refreshSavedSummaries", handler);
    return () => window.removeEventListener("refreshSavedSummaries", handler);
  }, []);

  useEffect(() => {
    const detailId = active?._id || active?.video_id || null;
    if (detailId) fetchDetail(detailId);
    else setActiveDetail(null);
  }, [active?._id, active?.video_id]);

  async function renameItem(id, currentTitle) {
    const name = window.prompt("Rename summary", currentTitle || "");
    if (!name) return;
    try {
      const res = await fetch(`${API_BASE}/api/my-summaries/${id}/rename`, {
        method: "PATCH",
        headers: getAuthHeaders(true),
        body: JSON.stringify({ title: name }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Rename failed");
      await fetchSummaries();
    } catch (e) {
      setErr(e.message);
    }
  }

  if (loading) return <div style={{ padding: 16 }}>Loading...</div>;
  if (err) return <div style={{ padding: 16, color: "#b91c1c" }}>{err}</div>;
  if (!items.length) return <div style={{ padding: 16 }}>No saved summaries yet.</div>;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "280px 1fr",
        gap: 16,
        maxWidth: 1100,
        margin: "16px auto",
      }}
    >
      {/* Sidebar */}
      <aside style={{ borderRight: "1px solid rgba(0,0,0,0.06)", paddingRight: 12 }}>
        <h3 style={{ marginTop: 0 }}>My Notes</h3>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((s) => (
            <li
              
              key={s._id || s.video_id}
              onClick={() => setActive(s)}
              style={{
                padding: "10px 8px",
                borderRadius: 8,
                marginBottom: 6,
                cursor: "pointer",
                background:
                  (active?._id || active?.video_id) === (s._id || s.video_id)
                    ? "rgba(16,185,129,0.08)"
                    : "transparent",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                }}
              >
                <div>
                  <strong style={{ display: "block" }}>{s.title}</strong>
                  <small style={{ color: "#666" }}>
                    {s.created_at ? new Date(s.created_at).toLocaleString() : ""}
                  </small>
                  <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>
                    {s.type === "text" ? "📝 Text" : "🎬 Video"}
                  </div>
                </div>

                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    renameItem(s._id, s.title);
                  }}
                  style={{
                    padding: "6px 10px",
                    borderRadius: 8,
                    border: "1px solid rgba(0,0,0,0.08)",
                    cursor: "pointer",
                    background: "#fff",
                  }}
                >
                  Rename
                </button>
              </div>
            </li>
          ))}
        </ul>
      </aside>

      {/* Main Content */}
      <main style={{ paddingLeft: 8 }}>
        {!active ? (
          <p>Select a note from the left.</p>
        ) : (
          <>
            <h2 style={{ marginTop: 0 }}>{activeDetail?.title || active.title}</h2>

            <div style={{ marginBottom: 8, color: "#666" }}>
              {active.video_url && (
                <a href={active.video_url} target="_blank" rel="noreferrer">
                  Open video ↗
                </a>
              )}
            </div>

            {detailLoading ? (
              <div>Loading note…</div>
            ) : activeDetail?.notes ? (
              <div
                style={{
                  padding: 12,
                  border: "1px solid rgba(0,0,0,0.06)",
                  borderRadius: 8,
                }}
              >
                <ReactMarkdown>{activeDetail.notes}</ReactMarkdown>
              </div>
            ) : (
              <p>No notes found for this item.</p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
