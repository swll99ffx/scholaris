import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { fetchHealth } from "../api/client";
import type { Health } from "../api/types";
import { useTheme } from "../hooks/useTheme";
import { useLibrary } from "../modules/library/LibraryContext";
import { Icon, type IconName } from "./Icon";

export interface NavItem {
  to: string;
  label: string;
  shortLabel: string;
  icon: IconName;
  module: number;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/research", label: "Source Finder", shortLabel: "Research", icon: "search", module: 1 },
  { to: "/summarize", label: "Source Summarizer", shortLabel: "Summarize", icon: "summary", module: 2 },
  { to: "/math", label: "Math & Physics", shortLabel: "Math", icon: "math", module: 3 },
  { to: "/data", label: "Data Analyst", shortLabel: "Data", icon: "data", module: 4 },
  { to: "/biology", label: "Biology Lab", shortLabel: "Biology", icon: "biology", module: 5 },
  { to: "/chat", label: "AI Study Chat", shortLabel: "Chat", icon: "chat", module: 6 },
];

type BackendStatus = "checking" | "online" | "offline";

function useBackend(): { status: BackendStatus; ai: Health["ai"] | null } {
  const [status, setStatus] = useState<BackendStatus>("checking");
  const [ai, setAi] = useState<Health["ai"] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    fetchHealth()
      .then((health) => {
        if (!cancelled) {
          setStatus("online");
          setAi(health.ai);
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("offline");
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  return { status, ai };
}

const AI_LABELS: Record<string, string> = {
  key: "AI: your key",
  free: "AI: online (free)",
  off: "AI: offline",
};

export function Layout({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const { status: backend, ai } = useBackend();
  const { items } = useLibrary();

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const statusLabel =
    backend === "online" ? "API online" : backend === "offline" ? "API offline" : "Checking API…";

  return (
    <div className="app-shell">
      <header className="mobile-header">
        <button
          type="button"
          className="icon-button"
          aria-label="Open navigation"
          onClick={() => setMenuOpen(true)}
        >
          <Icon name="menu" size={22} />
        </button>
        <span className="mobile-brand">Scholaris</span>
        <button type="button" className="icon-button" aria-label="Toggle theme" onClick={toggle}>
          <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
        </button>
      </header>

      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <Icon name="logo" size={20} />
          </div>
          <div>
            <div className="brand-name">Scholaris</div>
            <div className="brand-tag">Study smarter, not harder</div>
          </div>
        </div>

        <nav className="nav" aria-label="Modules">
          <p className="nav-section">Modules</p>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
            >
              <Icon name={item.icon} size={18} />
              <span className="nav-label">{item.label}</span>
              <span className="nav-module">M{item.module}</span>
            </NavLink>
          ))}

          <p className="nav-section">Your research</p>
          <NavLink
            to="/library"
            className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
          >
            <Icon name="book" size={18} />
            <span className="nav-label">My Library (RRL)</span>
            <span className="nav-module">{items.length}</span>
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="theme-toggle" onClick={toggle}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          <div className={`backend-status backend-${backend}`}>
            <span className="status-dot" />
            {statusLabel}
          </div>
          {backend === "online" && ai ? (
            <div className={`backend-status ai-${ai}`}>{AI_LABELS[ai]}</div>
          ) : null}
        </div>
      </aside>

      {menuOpen && (
        <div className="sidebar-backdrop" role="presentation" onClick={() => setMenuOpen(false)} />
      )}

      <main className="content">
        <div className="content-inner">{children}</div>
      </main>
    </div>
  );
}
