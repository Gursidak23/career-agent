import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type SettingsStatus } from "./api/client";
import { ToastProvider } from "./components/Toast";
import { Icon, type IconName } from "./components/ui";
import Jobs from "./pages/Jobs";
import Outreach from "./pages/Outreach";
import ResumeOptimizer from "./pages/ResumeOptimizer";
import Settings from "./pages/Settings";
import Tracker from "./pages/Tracker";

const NAV: { to: string; label: string; icon: IconName; step?: number }[] = [
  { to: "/resume", label: "Resume", icon: "resume", step: 1 },
  { to: "/jobs", label: "Jobs", icon: "jobs", step: 2 },
  { to: "/outreach", label: "Outreach", icon: "outreach", step: 3 },
  { to: "/tracker", label: "Tracker", icon: "history", step: 4 },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function SetupStatus({ status }: { status: SettingsStatus | null }) {
  if (!status) return null;
  const llm = status.providers.some((p) => p.configured);
  const items = [
    { ok: llm, label: llm ? "AI ready" : "No AI provider" },
    { ok: status.smtp_configured, label: status.smtp_configured ? "Email ready" : "Email not set up" },
  ];
  return (
    <NavLink to="/settings" className="setup-status" title="Open Settings">
      {items.map((i) => (
        <span key={i.label}>
          <i className={`dot ${i.ok ? "ok" : "bad"}`} />
          {i.label}
        </span>
      ))}
    </NavLink>
  );
}

export default function App() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <ToastProvider>
      <div className="app">
        <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
          <div className="brand">
            <span className="brand-mark">CA</span>
            <span>Career Agent</span>
            <button
              className="icon-btn menu-toggle"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle navigation"
              aria-expanded={menuOpen}
            >
              <Icon name="menu" />
            </button>
          </div>
          <nav className="nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to}>
                <Icon name={n.icon} />
                <span>{n.label}</span>
                {n.step && <span className="nav-step">{n.step}</span>}
              </NavLink>
            ))}
          </nav>
          <SetupStatus status={status} />
        </aside>
        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/resume" replace />} />
            <Route path="/resume" element={<ResumeOptimizer />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/outreach" element={<Outreach status={status} />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/settings" element={<Settings onStatus={setStatus} />} />
            <Route path="*" element={<Navigate to="/resume" replace />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
