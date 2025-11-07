// src/components/NavBar.js
import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import ProfileMenu from "./ProfileMenu";
import "./NavBar.css";

export default function NavBar({ user, apiBase, onLogout }) {
  const navigate = useNavigate();

  return (
    <nav className="nav-bar">
      <div className="nav-inner">
        <span className="brand" onClick={() => navigate("/app")}>
          📘 Study Hub
        </span>

        <div className="nav-links">
          <NavLink to="/app" end className="nav-link">Home</NavLink>
          <NavLink to="/app/my-summaries" className="nav-link">My Notes</NavLink>
          <NavLink to="/app/weak-areas" className="nav-link">Weak Areas</NavLink>
        </div>

        <div className="nav-profile">
          <ProfileMenu user={user} apiBase={apiBase} onLogout={onLogout} />
        </div>
      </div>
    </nav>
  );
}
