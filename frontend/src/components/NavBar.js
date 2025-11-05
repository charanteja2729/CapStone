// src/components/NavBar.js
import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';


export default function NavBar() {
  const navigate = useNavigate();

  const linkBase = {
    padding: '8px 12px',
    borderRadius: 8,
    textDecoration: 'none',
    fontSize: 14,
  };

  return (
    <nav
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        background: 'rgba(255,255,255,0.9)',
        backdropFilter: 'blur(6px)',
        borderBottom: '1px solid rgba(0,0,0,0.06)',
      }}
    >
      <div
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '10px 16px',
        }}
      >
        <span
          onClick={() => navigate('/app')}
          style={{ fontWeight: 800, fontSize: 18, cursor: 'pointer' }}
        >
          📘 Study Hub
        </span>

        <NavLink
          to="/app"
          end
          style={({ isActive }) => ({
            ...linkBase,
            color: isActive ? '#0b5' : '#222',
            background: isActive ? 'rgba(16,185,129,0.1)' : 'transparent',
          })}
        >
          Home
        </NavLink>

        <NavLink
          to="/app/my-summaries"
          style={({ isActive }) => ({
            ...linkBase,
            color: isActive ? '#0b5' : '#222',
            background: isActive ? 'rgba(16,185,129,0.1)' : 'transparent',
          })}
        >
          My Notes
        </NavLink>

        <NavLink
          to="/app/weak-areas"
          style={({ isActive }) => ({
            ...linkBase,
            color: isActive ? '#0b5' : '#222',
            background: isActive ? 'rgba(16,185,129,0.1)' : 'transparent',
          })}
        >
          Weak Areas
        </NavLink>
      </div>
    </nav>
  );
}
