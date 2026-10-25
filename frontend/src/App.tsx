import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, setApiToken, type Health, type SettingsStatus } from "./api/client";
import { ToastProvider } from "./components/Toast";
import { Icon, type IconName } from "./components/ui";
import Jobs from "./pages/Jobs";
import Outreach from "./pages/Outreach";
import ResumeOptimizer from "./pages/ResumeOptimizer";
import Settings from "./pages/Settings";
import Drill from "./pages/Drill";
import System from "./pages/System";
import Tracker from "./pages/Tracker";

const NAV: { to: string; label: string; icon: IconName; step?: number }[] = [
  { to: "/resume", label: "Resume", icon: "resume", step: 1 },
  { to: "/jobs", label: "Jobs", icon: "jobs", step: 2 },
  { to: "/outreach", label: "Outreach", icon: "outreach", step: 3 },
  { to: "/tracker", label: "Tracker", icon: "history", step: 4 },
  { to: "/drill", label: "Interview drill", icon: "sparkle", step: 5 },
  { to: "/system", label: "System", icon: "refresh" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function SetupStatus({ status, health }: { status: SettingsStatus | null; health: Health | null }) {
  if (!status) return null;
  const llm = status.providers.some((p) => p.configured);
  const items = [
    { ok: llm, label: llm ? "AI ready" : "No AI provider" },
    { ok: status.smtp_configured, label: status.smtp_configured ? "Email ready" : "Email not set up" },
  ];
  if (health) {
    items.push({ ok: health.worker.alive, label: health.worker.alive ? "Worker running" : "Worker stopped" });
    if (health.automation_paused) items.push({ ok: false, label: "Sending paused" });
  }
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
  const [health, setHealth] = useState<Health | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [token, setToken] = useState("");
  const location = useLocation();

  useEffect(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
    const poll = () => api.health().then(setHealth).catch(() => setHealth(null));
    poll();
    const t = window.setInterval(poll, 30000);
    const onUnauthorized = () => setNeedsToken(true);
    window.addEventListener("ca:unauthorized", onUnauthorized);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("ca:unauthorized", onUnauthorized);
    };
  }, []);
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <ToastProvider>
      {needsToken && (
        <div className="auth-gate" role="dialog" aria-modal="true" aria-labelledby="auth-title">
          <form
            className="card"
            onSubmit={(e) => {
              e.preventDefault();
              setApiToken(token.trim());
              window.location.reload();
            }}
          >
            <h2 id="auth-title">Access token required</h2>
            <p className="muted small">
              This Career Agent is protected. Enter the CAREER_API_TOKEN from its backend/.env.
            </p>
            <div className="field">
              <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus aria-label="Access token" />
            </div>
            <button type="submit" disabled={!token.trim()}>
              Unlock
            </button>
          </form>
        </div>
      )}
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
          <SetupStatus status={status} health={health} />
        </aside>
        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/resume" replace />} />
            <Route path="/resume" element={<ResumeOptimizer />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/outreach" element={<Outreach status={status} />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/drill" element={<Drill />} />
            <Route path="/system" element={<System />} />
            <Route path="/settings" element={<Settings onStatus={setStatus} />} />
            <Route path="*" element={<Navigate to="/resume" replace />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
