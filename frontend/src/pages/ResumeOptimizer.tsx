import { useEffect, useRef, useState, type DragEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  api,
  errorMessage,
  type AtsReport,
  type JobOut,
  type ResumeData,
  type ResumeSummary,
  type RoleOption,
  type TailoringSummary,
  type TailorResponse,
  type UploadResponse,
} from "../api/client";
import AtsReportView from "../components/AtsReportView";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner, scoreTone } from "../components/ui";
import { formatDate, titleCase, useDebounced, useElapsed, usePersistentState } from "../lib/hooks";

// Typical wall time for a tailoring run; drives the (approximate) progress bar.
const EXPECTED_TAILOR_SECONDS = 25;

export default function ResumeOptimizer() {
  const toast = useToast();
  const nav = useNavigate();
  const location = useLocation();

  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [resumeId, setResumeId] = usePersistentState<number | null>("ca.resumeId", null);
  const [resume, setResume] = useState<UploadResponse | null>(null);
  const [role, setRole] = usePersistentState("ca.role", "software_developer");
  const [jd, setJd] = usePersistentState("ca.jd", "");
  const [targetJob, setTargetJob] = usePersistentState<JobOut | null>("ca.targetJob", null);
  const [lastTailoringId, setLastTailoringId] = usePersistentState<number | null>("lastTailoringId", null);
  const [history, setHistory] = useState<TailoringSummary[]>([]);
  const [result, setResult] = useState<TailorResponse | null>(null);
  const [liveScore, setLiveScore] = useState<AtsReport | null>(null);
  const [uploading, setUploading] = useState(false);
  const [tailoring, setTailoring] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const uploadSeconds = useElapsed(uploading);
  const tailorSeconds = useElapsed(tailoring);
  const debouncedJd = useDebounced(jd, 500);

  useEffect(() => {
    api.roles().then(setRoles).catch((e) => toast.err(errorMessage(e)));
    api.resumes().then(setResumes).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Arriving from the Jobs page with a posting: target it.
  useEffect(() => {
    const job = (location.state as { job?: JobOut } | null)?.job;
    if (!job) return;
    setTargetJob(job);
    setJd([`${job.title} at ${job.company}`, job.description || ""].join("\n\n").trim());
    if (job.role_category && roles.some((r) => r.key === job.role_category)) {
      setRole(job.role_category);
    }
    setResult(null);
    nav(location.pathname, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, roles]);

  // Load the active resume, its history, and the last result for it.
  useEffect(() => {
    if (resumeId == null) {
      setResume(null);
      setHistory([]);
      return;
    }
    api
      .resume(resumeId)
      .then(setResume)
      .catch(() => setResumeId(null));
    api
      .tailorings(resumeId)
      .then((rows) => {
        setHistory(rows);
        if (lastTailoringId && rows.some((r) => r.id === lastTailoringId) && !result) {
          api.tailoring(lastTailoringId).then(setResult).catch(() => {});
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId]);

  // Live (instant, no AI) score of the current resume for the chosen target.
  useEffect(() => {
    if (!resume) {
      setLiveScore(null);
      return;
    }
    let stale = false;
    api
      .score({ resume: resume.parsed, role, job_description: debouncedJd || undefined })
      .then((r) => !stale && setLiveScore(r))
      .catch(() => !stale && setLiveScore(null));
    return () => {
      stale = true;
    };
  }, [resume, role, debouncedJd]);

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.err("Please choose a PDF file.");
      return;
    }
    setUploading(true);
    try {
      const res = await api.upload(file);
      setResult(null);
      setResume(res);
      setResumeId(res.resume_id);
      if (res.warning) toast.warn(res.warning);
      else if (res.reused) toast.info("Same PDF as before, so the saved parse was reused instantly.");
      else toast.ok("Resume parsed.");
      api.resumes().then(setResumes).catch(() => {});
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  }

  async function optimize() {
    if (!resume) return;
    setTailoring(true);
    try {
      const res = await api.tailor({
        resume_id: resume.resume_id,
        role,
        job_description: jd.trim() || undefined,
      });
      setResult(res);
      setLastTailoringId(res.tailoring_id);
      if (res.warning) toast.warn(res.warning);
      else toast.ok(`Optimized: ATS score ${Math.round(res.ats.score)}.`);
      api.tailorings(resume.resume_id).then(setHistory).catch(() => {});
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setTailoring(false);
    }
  }

  async function openTailoring(id: number) {
    try {
      const res = await api.tailoring(id);
      setResult(res);
      setLastTailoringId(id);
      setRole(res.role);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  function clearTarget() {
    setTargetJob(null);
    setJd("");
  }

  const p = resume?.parsed;
  const completeResumes = resumes.filter((r) => r.complete);
  const roleLabel = roles.find((r) => r.key === role)?.label ?? role;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Resume optimizer</h1>
          <p className="subtitle">
            Rebuild your resume for a role or a specific job post, scored against an ATS rubric.
            Nothing is invented; your real experience is just reworded to match.
          </p>
        </div>
      </div>

      <div className="grid-main">
        <div style={{ minWidth: 0 }}>
          {/* ---------- Step 1: resume ---------- */}
          <div className="card">
            <div className="card-header">
              <div className="step-title">
                <span className={`step-num ${p ? "done" : ""}`}>{p ? <Icon name="check" size={14} /> : 1}</span>
                <h2>Your resume</h2>
              </div>
              {p && (
                <button className="secondary sm" onClick={() => fileInput.current?.click()} disabled={uploading}>
                  <Icon name="upload" size={15} /> Upload another
                </button>
              )}
            </div>

            {p ? (
              <div className="parsed-summary">
                <span className="avatar">
                  {(p.contact.name || "?")
                    .split(/\s+/)
                    .map((w) => w[0])
                    .slice(0, 2)
                    .join("")
                    .toUpperCase()}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{titleCase(p.contact.name || "Unnamed resume")}</strong>
                  <div className="muted small">
                    {p.experience.length} roles · {p.projects.length} projects · {p.education.length} education ·{" "}
                    {p.skills.length} skills
                  </div>
                </div>
                {completeResumes.length > 1 && (
                  <select
                    style={{ width: "auto" }}
                    value={resumeId ?? ""}
                    onChange={(e) => {
                      setResult(null);
                      setResumeId(Number(e.target.value));
                    }}
                    aria-label="Switch resume"
                  >
                    {completeResumes.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.filename || `Resume #${r.id}`} · {formatDate(r.created_at)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            ) : (
              <>
                <div
                  className={`dropzone ${dragging ? "drag" : ""}`}
                  onClick={() => !uploading && fileInput.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
                >
                  {uploading ? (
                    <>
                      <Spinner size={22} />
                      <strong>Reading your resume… {uploadSeconds}s</strong>
                      <span className="small">AI parsing usually takes about 10 seconds.</span>
                    </>
                  ) : (
                    <>
                      <Icon name="upload" size={26} />
                      <strong>Drop your resume PDF here</strong>
                      <span className="small">or click to browse</span>
                    </>
                  )}
                </div>
                {completeResumes.length > 0 && (
                  <div className="field" style={{ marginTop: 12, marginBottom: 0 }}>
                    <label htmlFor="prev-resume">Or use a previous upload</label>
                    <select
                      id="prev-resume"
                      value=""
                      onChange={(e) => e.target.value && setResumeId(Number(e.target.value))}
                    >
                      <option value="">Choose…</option>
                      {completeResumes.map((r) => (
                        <option key={r.id} value={r.id}>
                          {titleCase(r.name) || r.filename} · {r.filename} · {formatDate(r.created_at)}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </>
            )}
            {uploading && p && (
              <div className="callout" style={{ marginTop: 12, marginBottom: 0 }}>
                <Spinner /> Reading the new resume… {uploadSeconds}s
              </div>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
                e.target.value = "";
              }}
            />
          </div>

          {/* ---------- Step 2: target ---------- */}
          <div className="card">
            <div className="card-header">
              <div className="step-title">
                <span className="step-num">2</span>
                <h2>Target</h2>
              </div>
              {liveScore && (
                <span className="live-score" title="Instant score of your current resume for this target">
                  Current score
                  <strong className={scoreTone(liveScore.score)}>{Math.round(liveScore.score)}</strong>
                </span>
              )}
            </div>

            {targetJob && (
              <div className="callout" style={{ alignItems: "center" }}>
                <Icon name="jobs" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="truncate">
                    <strong>{targetJob.title}</strong> at {targetJob.company}
                  </div>
                  <div className="hint">Tailoring to this job post's description</div>
                </div>
                <button className="ghost sm" onClick={clearTarget}>
                  Clear
                </button>
              </div>
            )}

            <div className="field">
              <label htmlFor="role">Role</label>
              <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
                {roles.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="jd">Job description (optional, gives much more precise keywords)</label>
              <textarea
                id="jd"
                value={jd}
                onChange={(e) => setJd(e.target.value)}
                placeholder="Paste the job post here, or pick a job on the Jobs page…"
              />
            </div>
            <div className="spread">
              <span className="hint">
                {resume ? `Optimizing for ${roleLabel}${jd.trim() ? " + this job description" : ""}.` : "Add your resume first."}
              </span>
              <button className="lg" onClick={optimize} disabled={!resume || tailoring || uploading}>
                {tailoring ? <Spinner /> : <Icon name="sparkle" />}
                {tailoring ? "Optimizing…" : "Optimize resume"}
              </button>
            </div>
          </div>

          {tailoring && (
            <div className="progress">
              <Spinner size={22} />
              <div style={{ flex: 1 }}>
                <strong>
                  {tailorSeconds < 8
                    ? "Rewriting your bullets for this target…"
                    : tailorSeconds < 25
                    ? "Scoring the drafts and keeping the best…"
                    : "Running another pass to push the score higher…"}
                </strong>
                <span className="muted small">{tailorSeconds}s · usually under 30 seconds</span>
                <div className="progress-bar">
                  <div style={{ width: `${Math.min(95, (tailorSeconds / EXPECTED_TAILOR_SECONDS) * 100)}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* ---------- Results ---------- */}
          {result && !tailoring && (
            <>
              <div className="spread" style={{ margin: "26px 0 12px" }}>
                <h2 style={{ margin: 0 }}>
                  Result · {roles.find((r) => r.key === result.role)?.label ?? result.role}
                </h2>
                <div className="inline">
                  {result.pdf_available && (
                    <a className="btn sm" href={api.downloadUrl(result.tailoring_id, "pdf")} download>
                      <Icon name="download" size={15} /> PDF
                    </a>
                  )}
                  {result.docx_available && (
                    <a
                      className={`btn sm ${result.pdf_available ? "secondary" : ""}`}
                      href={api.downloadUrl(result.tailoring_id, "docx")}
                      download
                    >
                      <Icon name="download" size={15} /> Word
                    </a>
                  )}
                  <a className="btn secondary sm" href={api.downloadUrl(result.tailoring_id, "tex")} download>
                    .tex
                  </a>
                </div>
              </div>

              <AtsReportView report={result.ats} baseline={result.baseline_score} />

              <div className="card callout ok" style={{ alignItems: "center", padding: "14px 18px" }}>
                <Icon name="outreach" />
                <div style={{ flex: 1 }}>
                  <strong>Next: reach out to a recruiter</strong>
                  <div className="small muted">This resume will be attached automatically.</div>
                </div>
                <button
                  onClick={() => nav("/outreach", { state: { tailoringId: result.tailoring_id, job: targetJob } })}
                >
                  Write outreach <Icon name="arrow" size={15} />
                </button>
              </div>

              {resume && <ChangesView before={resume.parsed} after={result.tailored} />}
              <ResumePreview data={result.tailored} />
            </>
          )}

          {!result && !tailoring && resume && (
            <div className="card">
              <EmptyState icon={<Icon name="sparkle" />} title="No optimized version yet">
                Pick a role (and optionally paste a job description), then click Optimize resume.
              </EmptyState>
            </div>
          )}
        </div>

        {/* ---------- History ---------- */}
        <aside className="card" style={{ position: "sticky", top: 16 }}>
          <div className="card-header" style={{ marginBottom: 8 }}>
            <h2 className="inline">
              <Icon name="history" size={16} /> History
            </h2>
          </div>
          {history.length === 0 ? (
            <p className="muted small" style={{ margin: 0 }}>
              Optimized versions of this resume will appear here so you can reopen and download them later.
            </p>
          ) : (
            <div className="list">
              {history.map((h) => (
                <button
                  key={h.id}
                  className={`list-item ${result?.tailoring_id === h.id ? "active" : ""}`}
                  onClick={() => openTailoring(h.id)}
                >
                  <div className="grow">
                    <div className="truncate" style={{ fontWeight: 600 }}>
                      {h.role_label}
                    </div>
                    <div className="hint truncate">{h.job_snippet || "No job description"}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    {h.ats_score != null && (
                      <span className={`badge ${h.ats_score >= 90 ? "ok" : h.ats_score >= 70 ? "warn" : "bad"}`}>
                        {Math.round(h.ats_score)}
                      </span>
                    )}
                    <div className="hint">{formatDate(h.created_at)}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function ChangesView({ before, after }: { before: ResumeData; after: ResumeData }) {
  const lower = (xs: string[]) => new Set(xs.map((s) => s.toLowerCase()));
  const beforeSkills = lower(before.skills);
  const afterSkills = lower(after.skills);
  const added = after.skills.filter((s) => !beforeSkills.has(s.toLowerCase()));
  const removed = before.skills.filter((s) => !afterSkills.has(s.toLowerCase()));
  const bullets = (r: ResumeData) =>
    r.experience.reduce((n, e) => n + e.bullets.length, 0) +
    r.projects.reduce((n, p) => n + p.bullets.length, 0);

  return (
    <div className="card">
      <h2>What changed</h2>
      <div className="grid-2">
        <div>
          <div className="label" style={{ marginBottom: 8 }}>
            Skills surfaced
          </div>
          <div className="pills">
            {added.length ? added.map((s) => <span className="pill add" key={s}>+ {s}</span>) : <span className="muted small">None</span>}
          </div>
        </div>
        <div>
          <div className="label" style={{ marginBottom: 8 }}>
            Skills dropped
          </div>
          <div className="pills">
            {removed.length ? removed.map((s) => <span className="pill miss" key={s}>− {s}</span>) : <span className="muted small">None</span>}
          </div>
        </div>
      </div>
      <p className="muted small" style={{ margin: "14px 0 0" }}>
        Bullets: {bullets(before)} → {bullets(after)} · Summary{" "}
        {!after.summary ? "none" : before.summary === after.summary ? "unchanged" : before.summary ? "rewritten" : "added"}
      </p>
    </div>
  );
}

const STANDARD = ["summary", "experience", "projects", "skills", "education", "certifications"];

/** Section keys in the original resume's order, then any that order omits. */
function orderedSections(data: ResumeData): string[] {
  const extras = (data.extra_sections || []).map((x) => x.title);
  const all = [...STANDARD, ...extras];
  const byLower = new Map(all.map((k) => [k.toLowerCase(), k]));
  const out: string[] = [];
  for (const key of [...(data.section_order || []), ...all]) {
    const k = byLower.get(key.trim().toLowerCase());
    if (k && !out.includes(k)) out.push(k);
  }
  return out;
}

function ResumePreview({ data }: { data: ResumeData }) {
  const dates = (a?: string | null, b?: string | null) => [a, b].filter(Boolean).join(" – ");
  const section = (key: string) => {
    switch (key) {
      case "summary":
        return data.summary ? <p style={{ margin: 0 }}>{data.summary}</p> : null;
      case "experience":
        return data.experience.length
          ? data.experience.map((e, i) => (
              <div key={i}>
                <div className="spread">
                  <strong>
                    {e.company}
                    {e.location ? <span className="hint"> · {e.location}</span> : null}
                  </strong>
                  <span className="hint">{dates(e.start_date, e.end_date)}</span>
                </div>
                <em className="muted">{e.title}</em>
                <ul>{e.bullets.map((b, j) => <li key={j}>{b}</li>)}</ul>
              </div>
            ))
          : null;
      case "projects":
        return data.projects.length
          ? data.projects.map((p, i) => (
              <div key={i}>
                <div className="spread">
                  <strong>{p.name}</strong>
                  {p.link && (
                    <a href={p.link} target="_blank" rel="noreferrer" className="small">
                      {p.link.includes("github.com") ? "GitHub" : "Link"}
                    </a>
                  )}
                </div>
                {p.description && <div className="muted small">{p.description}</div>}
                <ul>{p.bullets.map((b, j) => <li key={j}>{b}</li>)}</ul>
              </div>
            ))
          : null;
      case "skills":
        if (data.skill_groups?.length)
          return data.skill_groups.map((g) => (
            <div key={g.category} style={{ marginBottom: 4 }}>
              <strong>{g.category}:</strong> {g.skills.join(", ")}
            </div>
          ));
        return data.skills.length ? (
          <div className="pills">{data.skills.map((s) => <span className="pill" key={s}>{s}</span>)}</div>
        ) : null;
      case "education":
        return data.education.length
          ? data.education.map((ed, i) => (
              <div key={i} style={{ marginBottom: 6 }}>
                <strong>{ed.degree}</strong>
                <div className="muted small">
                  {[ed.institution, ed.location, dates(ed.start_date, ed.end_date)].filter(Boolean).join(" | ")}
                </div>
                {ed.details && <div className="small" style={{ whiteSpace: "pre-line" }}>{ed.details}</div>}
              </div>
            ))
          : null;
      case "certifications":
        return data.certifications.length
          ? data.certifications.map((c, i) => (
              <div key={i}>
                {c.name}
                {c.date && <span className="hint"> | {c.date}</span>}
                {c.url && (
                  <>
                    {" "}| <a href={c.url} target="_blank" rel="noreferrer">View credential</a>
                  </>
                )}
              </div>
            ))
          : null;
      default: {
        const extra = data.extra_sections?.find((x) => x.title === key);
        return extra?.items.length ? extra.items.map((it, i) => <div key={i}>{it}</div>) : null;
      }
    }
  };
  const titles: Record<string, string> = {
    summary: "Summary",
    experience: "Experience",
    projects: "Projects",
    skills: data.skill_groups?.length ? "Technical skills" : "Skills",
    education: "Education",
    certifications: "Certifications",
  };

  return (
    <div className="card">
      <div className="spread">
        <h2 style={{ margin: 0 }}>Optimized resume</h2>
        <span className="hint">
          Same layout as your original
          {data.layout?.pages ? ` · ${data.layout.pages} page${data.layout.pages > 1 ? "s" : ""}` : ""}
        </span>
      </div>
      {data.contact.headline && (
        <p className="muted" style={{ margin: "8px 0 0" }}>
          <strong>{data.contact.headline}</strong>
        </p>
      )}
      {orderedSections(data).map((key) => {
        const body = section(key);
        return body ? (
          <div className="preview-section" key={key}>
            <h3>{titles[key] ?? key}</h3>
            {body}
          </div>
        ) : null;
      })}
    </div>
  );
}
