import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type BackupItem,
  type Health,
  type SystemEvent,
  type TaskOut,
  type Usage,
} from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";

const when = (iso?: string | null) => {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

const TASK_BADGE: Record<TaskOut["status"], string> = {
  queued: "",
  running: "accent",
  succeeded: "ok",
  failed: "bad",
  cancelled: "",
};

function Tile({ ok, title, children }: { ok: boolean; title: string; children: React.ReactNode }) {
  return (
    <div className="card tile">
      <div className="inline" style={{ gap: 8 }}>
        <i className={`dot ${ok ? "ok" : "bad"}`} />
        <strong>{title}</strong>
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>
        {children}
      </div>
    </div>
  );
}

export default function System() {
  const toast = useToast();
  const [health, setHealth] = useState<Health | null>(null);
  const [tasks, setTasks] = useState<TaskOut[]>([]);
  const [taskFilter, setTaskFilter] = useState<string>("");
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  async function loadFast() {
    try {
      const [h, t] = await Promise.all([api.health(), api.tasks(taskFilter || undefined)]);
      setHealth(h);
      setTasks(t);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }
  async function loadSlow() {
    try {
      const [e, u, b] = await Promise.all([api.events(60), api.usage(7), api.backups()]);
      setEvents(e);
      setUsage(u);
      setBackups(b);
    } catch {
      /* the fast loop reports connectivity problems */
    }
  }

  useEffect(() => {
    loadFast();
    const t = window.setInterval(loadFast, 5000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskFilter]);
  useEffect(() => {
    loadSlow();
    const t = window.setInterval(loadSlow, 15000);
    return () => window.clearInterval(t);
  }, []);

  async function act(label: string, fn: () => Promise<unknown>, done: string) {
    setBusy(label);
    try {
      await fn();
      toast.ok(done);
      await Promise.all([loadFast(), loadSlow()]);
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (!health) {
    return (
      <div className="card">
        <Spinner /> Checking the system…
      </div>
    );
  }

  const budgetPct = health.copilot_daily_budget > 0 ? Math.min(100, (100 * health.copilot_credits_today) / health.copilot_daily_budget) : 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>System</h1>
          <p className="subtitle">
            Health, background tasks, AI usage, activity and backups. The worker runs emails, tailoring, scheduled
            fetches and backups separately from the web server, so restarts don't lose work.
          </p>
        </div>
        <span className={`badge ${health.status === "ok" ? "ok" : "warn"}`}>
          {health.status === "ok" ? "All systems normal" : "Needs attention"}
        </span>
      </div>

      {health.problems.length > 0 && (
        <div className="callout warn">
          <ul className="issues" style={{ margin: 0 }}>
            {health.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="tiles">
        <Tile ok={health.database} title="Database">
          {health.database ? "Reachable (WAL mode)" : "Unreachable"}
        </Tile>
        <Tile ok={health.worker.alive} title="Worker">
          {health.worker.alive ? (
            `Running · ${health.worker.running} active · seen ${when(health.worker.last_heartbeat)}`
          ) : (
            <>
              Not running. Start it with <code>./run.sh</code> or <code>career-agent worker</code>.
            </>
          )}
        </Tile>
        <Tile ok={health.queue.failed_24h === 0} title="Queue">
          {health.queue.queued} queued · {health.queue.running} running · {health.queue.failed_24h} failed (24h)
        </Tile>
        <Tile ok={!!health.last_backup} title="Backups">
          Last: {when(health.last_backup)}
        </Tile>
        <Tile ok={budgetPct < 80} title="Copilot spend today">
          {health.copilot_credits_today.toFixed(3)} / {health.copilot_daily_budget} AI credits
          <div className="bar" style={{ marginTop: 6 }}>
            <div style={{ width: `${budgetPct}%` }} />
          </div>
        </Tile>
      </div>

      <div className="card">
        <div className="spread">
          <div>
            <h2 style={{ margin: 0 }}>Outgoing messages</h2>
            <div className="hint">
              Pausing stops every email and LinkedIn DM from leaving; they wait in the queue until you resume.
            </div>
          </div>
          <button
            className={health.automation_paused ? "" : "danger"}
            disabled={busy === "pause"}
            onClick={() =>
              act(
                "pause",
                () => api.setAutomation(!health.automation_paused),
                health.automation_paused ? "Sending resumed." : "Sending paused."
              )
            }
          >
            {health.automation_paused ? "Resume sending" : "Pause all sending"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>Background tasks</h2>
          <div className="tabs" role="tablist">
            {[
              ["", "All"],
              ["queued", "Queued"],
              ["running", "Running"],
              ["failed", "Failed"],
            ].map(([v, l]) => (
              <button key={v} role="tab" aria-selected={taskFilter === v} className={taskFilter === v ? "active" : ""} onClick={() => setTaskFilter(v)}>
                {l}
              </button>
            ))}
          </div>
        </div>
        {tasks.length === 0 ? (
          <EmptyState title="No tasks here" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id}>
                    <td style={{ maxWidth: 420 }}>
                      <div className="truncate">
                        <span className="hint">#{t.id}</span> {t.summary}
                      </div>
                      {(t.error || t.progress) && (
                        <div className={`hint ${t.status === "failed" ? "" : ""}`} style={{ overflowWrap: "anywhere" }}>
                          {t.status === "failed" || t.status === "queued" ? t.error || t.progress : t.progress}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${TASK_BADGE[t.status]}`}>{t.status}</span>
                      {t.attempts > 1 && <div className="hint">try {t.attempts}/{t.max_attempts}</div>}
                    </td>
                    <td className="hint">{t.status === "queued" ? `due ${when(t.run_at)}` : when(t.finished_at || t.created_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {t.status === "queued" && (
                        <button className="ghost sm" onClick={() => act(`c${t.id}`, () => api.cancelTask(t.id), "Cancelled.")}>
                          Cancel
                        </button>
                      )}
                      {(t.status === "failed" || t.status === "cancelled") && (
                        <button className="secondary sm" onClick={() => act(`r${t.id}`, () => api.retryTask(t.id), "Queued again.")}>
                          <Icon name="refresh" size={14} /> Retry
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card">
          <h2>AI usage (7 days)</h2>
          {!usage || usage.providers.length === 0 ? (
            <EmptyState title="No AI calls recorded yet" />
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Provider</th>
                      <th>Calls</th>
                      <th>Avg</th>
                      <th>Tokens</th>
                      <th>Credits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.providers.map((p) => (
                      <tr key={p.provider}>
                        <td>
                          {p.provider}
                          {p.fallbacks > 0 && <div className="hint">{p.fallbacks} after a fallback</div>}
                        </td>
                        <td>
                          {p.ok}/{p.calls}
                        </td>
                        <td className="hint">{(p.avg_latency_ms / 1000).toFixed(1)}s</td>
                        <td className="hint">{(p.input_tokens + p.output_tokens).toLocaleString()}</td>
                        <td>{p.credits ? p.credits.toFixed(3) : "free"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pills" style={{ marginTop: 10 }}>
                {Object.entries(usage.by_purpose).map(([k, v]) => (
                  <span key={k} className="pill">
                    {k}: {v}
                  </span>
                ))}
              </div>
              {usage.recent_errors.length > 0 && (
                <details style={{ marginTop: 10 }}>
                  <summary className="small">Recent AI errors ({usage.recent_errors.length})</summary>
                  <ul className="issues">
                    {usage.recent_errors.map((e, i) => (
                      <li key={i}>
                        <span className="hint">{when(e.created_at)} · {e.purpose}:</span> {e.error}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <h2>Backups</h2>
            <button className="secondary sm" disabled={busy === "backup"} onClick={() => act("backup", api.backupNow, "Backup queued.")}>
              {busy === "backup" ? <Spinner /> : null} Back up now
            </button>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            Daily and automatic: the database plus your uploaded resumes, newest 14 kept in backend/data/backups.
          </p>
          {backups.length === 0 ? (
            <EmptyState title="No backups yet" />
          ) : (
            backups.slice(0, 6).map((b) => (
              <div key={b.name} className="queue-item">
                <span style={{ flex: 1 }}>{when(b.created_at)}</span>
                <span className="hint">{(b.size / 1024).toFixed(0)} KB</span>
                <a className="btn secondary sm" href={api.backupUrl(b.name)} download>
                  <Icon name="download" size={14} />
                </a>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="card">
        <h2>Activity</h2>
        {events.length === 0 ? (
          <EmptyState title="Nothing recorded yet" />
        ) : (
          <div className="activity">
            {events.map((e) => (
              <div key={e.id} className="activity-row">
                <i className={`dot ${e.level === "info" ? "ok" : "bad"}`} style={e.level === "error" ? { background: "var(--bad)", boxShadow: "0 0 0 3px var(--bad-soft)" } : undefined} />
                <span className="hint activity-time">{when(e.created_at)}</span>
                <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{e.message}</span>
                <span className="badge">{e.kind}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
