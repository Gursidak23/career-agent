import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  APPLICATION_STATUSES,
  errorMessage,
  type ApplicationOut,
  type ApplicationStatus,
} from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";
import { formatDate, usePersistentState } from "../lib/hooks";

const LABELS: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  contacted: "Contacted",
  replied: "Replied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

const TONE: Record<ApplicationStatus, string> = {
  saved: "",
  applied: "accent",
  contacted: "accent",
  replied: "warn",
  interview: "warn",
  offer: "ok",
  rejected: "bad",
};

type Filter = ApplicationStatus | "active" | "all";

export default function Tracker() {
  const toast = useToast();
  const nav = useNavigate();
  const [apps, setApps] = useState<ApplicationOut[] | null>(null);
  const [filter, setFilter] = usePersistentState<Filter>("ca.trackerFilter", "active");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ company: "", role: "", url: "" });
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load() {
    try {
      setApps(await api.applications());
    } catch (e) {
      toast.err(errorMessage(e));
      setApps([]);
    }
  }

  function replace(updated: ApplicationOut) {
    setApps((all) => (all || []).map((a) => (a.id === updated.id ? updated : a)));
  }

  async function setStatus(app: ApplicationOut, status: ApplicationStatus) {
    try {
      replace(await api.updateApplication(app.id, { status }));
      toast.ok(`${app.company}: ${LABELS[status]}`);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  async function saveNotes(app: ApplicationOut, notes: string) {
    if ((app.notes || "") === notes) return;
    try {
      replace(await api.updateApplication(app.id, { notes }));
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  async function remove(app: ApplicationOut) {
    try {
      await api.deleteApplication(app.id);
      setApps((all) => (all || []).filter((a) => a.id !== app.id));
      setConfirmDelete(null);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  async function addManual() {
    try {
      const app = await api.createApplication({
        company: draft.company.trim(),
        role: draft.role.trim(),
        url: draft.url.trim() || undefined,
      });
      setApps((all) => [app, ...(all || []).filter((a) => a.id !== app.id)]);
      setDraft({ company: "", role: "", url: "" });
      setAdding(false);
      toast.ok(`Tracking ${app.role} at ${app.company}.`);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  async function openJob(app: ApplicationOut, to: "/resume" | "/outreach") {
    try {
      const job = app.job_id
        ? await api.job(app.job_id)
        : { id: 0, source: "manual", title: app.role, company: app.company, url: app.url };
      nav(to, {
        state: {
          job: job.id ? job : { ...job, id: undefined },
          tailoringId: to === "/outreach" ? app.tailoring_id ?? undefined : undefined,
        },
      });
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: apps?.length || 0, active: 0 };
    for (const a of apps || []) {
      c[a.status] = (c[a.status] || 0) + 1;
      if (a.status !== "rejected" && a.status !== "offer") c.active += 1;
    }
    return c;
  }, [apps]);

  const shown = (apps || []).filter((a) =>
    filter === "all" ? true : filter === "active" ? a.status !== "rejected" && a.status !== "offer" : a.status === filter
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Tracker</h1>
          <p className="subtitle">
            Every job you're pursuing, from saved to offer. Tailoring a resume for a job adds it here, and sending
            an email moves it to Contacted.
          </p>
        </div>
        <button className="secondary" onClick={() => setAdding((a) => !a)}>
          {adding ? "Cancel" : "+ Add manually"}
        </button>
      </div>

      {adding && (
        <div className="card">
          <div className="row">
            <div className="field">
              <label htmlFor="t-company">Company *</label>
              <input id="t-company" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="t-role">Role *</label>
              <input id="t-role" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} />
            </div>
            <div className="field" style={{ flex: "2 1 220px" }}>
              <label htmlFor="t-url">Posting URL</label>
              <input id="t-url" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} placeholder="https://…" />
            </div>
            <button onClick={addManual} disabled={!draft.company.trim() || !draft.role.trim()}>
              Add
            </button>
          </div>
        </div>
      )}

      <div className="pipeline" role="tablist" aria-label="Filter by status">
        {(["active", ...APPLICATION_STATUSES, "all"] as Filter[]).map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            className={filter === f ? "active" : ""}
            onClick={() => setFilter(f)}
          >
            {f === "active" ? "Active" : f === "all" ? "All" : LABELS[f]}
            <span className="count">{counts[f] || 0}</span>
          </button>
        ))}
      </div>

      {apps === null ? (
        <div className="card">
          <Spinner /> Loading…
        </div>
      ) : shown.length === 0 ? (
        <div className="card">
          <EmptyState icon={<Icon name="jobs" />} title={apps.length ? "Nothing in this stage" : "No applications yet"}>
            {apps.length
              ? "Pick another stage above."
              : "Click Track on a job, tailor your resume to one, or add one manually."}
          </EmptyState>
        </div>
      ) : (
        <div className="tracker-grid">
          {shown.map((a) => (
            <div className="card tracker-card" key={a.id}>
              <div className="spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  {a.url ? (
                    <a className="job-title" href={a.url} target="_blank" rel="noreferrer">
                      {a.role} <Icon name="external" size={13} />
                    </a>
                  ) : (
                    <span className="job-title">{a.role}</span>
                  )}
                  <div className="job-meta">
                    <strong style={{ color: "var(--text)", fontWeight: 500 }}>{a.company}</strong>
                    {a.location && <span>{a.location}</span>}
                  </div>
                </div>
                <select
                  className={`status-select ${TONE[a.status]}`}
                  value={a.status}
                  onChange={(e) => setStatus(a, e.target.value as ApplicationStatus)}
                  aria-label={`Status for ${a.role} at ${a.company}`}
                >
                  {APPLICATION_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {LABELS[s]}
                    </option>
                  ))}
                </select>
                <button className="icon-btn" onClick={() => setConfirmDelete(a.id)} aria-label="Remove from tracker">
                  <Icon name="x" size={16} />
                </button>
              </div>

              {confirmDelete === a.id && (
                <div className="callout bad" style={{ marginTop: 10, marginBottom: 0, alignItems: "center" }}>
                  <span style={{ flex: 1 }}>Remove this from the tracker?</span>
                  <button className="danger sm" onClick={() => remove(a)}>
                    Remove
                  </button>
                  <button className="ghost sm" onClick={() => setConfirmDelete(null)}>
                    Keep
                  </button>
                </div>
              )}

              <div className="job-meta" style={{ marginTop: 8 }}>
                {a.tailoring_score != null && <span className="badge accent">Resume {Math.round(a.tailoring_score)}</span>}
                {a.emails_sent > 0 && (
                  <span className="badge" title={a.recruiter_email || ""}>
                    <Icon name="mail" size={12} /> {a.emails_sent} sent
                  </span>
                )}
                <span className="hint">
                  Saved {formatDate(a.created_at)}
                  {a.applied_at && ` · Applied ${formatDate(a.applied_at)}`}
                  {a.last_emailed_at && ` · Emailed ${formatDate(a.last_emailed_at)}`}
                </span>
              </div>

              <textarea
                className="notes"
                defaultValue={a.notes || ""}
                placeholder="Notes: referral, interview date, contacts…"
                onBlur={(e) => saveNotes(a, e.target.value)}
                aria-label="Notes"
              />

              <div className="inline" style={{ marginTop: 8 }}>
                <button className="secondary sm" onClick={() => openJob(a, "/resume")}>
                  <Icon name="sparkle" size={14} /> Tailor
                </button>
                <button className="secondary sm" onClick={() => openJob(a, "/outreach")}>
                  <Icon name="outreach" size={14} /> Outreach
                </button>
                {a.tailoring_id && (
                  <a className="btn secondary sm" href={api.downloadUrl(a.tailoring_id, "pdf")} download>
                    <Icon name="download" size={14} /> Resume
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
