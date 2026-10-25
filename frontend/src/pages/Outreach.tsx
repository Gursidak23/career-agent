import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  errorMessage,
  type EmailCandidateOut,
  type EmailLogOut,
  type GeneratedMessage,
  type JobOut,
  type LinkedInLogOut,
  type LinkedInStatus,
  type SendItem,
  type SettingsStatus,
  type TailoringSummary,
} from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";
import { formatDate, useElapsed, usePersistentState } from "../lib/hooks";

interface LiQueueItem {
  profile_url: string;
  message: string;
  recipient_name?: string;
}

const EMPTY_FORM = {
  recruiter_name: "",
  recruiter_email: "",
  company: "",
  role: "",
  channel: "email",
  candidate_name: "",
  highlights: "",
  tone: "professional",
  variants: 2,
};

const statusBadge = (s: string) => (s === "sent" ? "ok" : s === "failed" ? "bad" : s === "pending" ? "warn" : "");

export default function Outreach({ status }: { status: SettingsStatus | null }) {
  const location = useLocation();
  const nav = useNavigate();
  const toast = useToast();

  const [form, setForm] = usePersistentState("ca.outreachForm", EMPTY_FORM);
  const [job, setJob] = usePersistentState<JobOut | null>("ca.outreachJob", null);
  const [attachId, setAttachId] = usePersistentState<number | null>("lastTailoringId", null);
  const [messages, setMessages] = usePersistentState<GeneratedMessage[]>("ca.outreachMessages", []);
  const [queue, setQueue] = usePersistentState<SendItem[]>("ca.emailQueue", []);
  const [dryRun, setDryRun] = useState(true);
  const [allowRepeat, setAllowRepeat] = useState(false);
  const [paused, setPaused] = useState(false);
  const [tailorings, setTailorings] = useState<TailoringSummary[]>([]);
  const [sends, setSends] = useState<EmailLogOut[]>([]);
  const [candidates, setCandidates] = useState<EmailCandidateOut[]>([]);
  const [finding, setFinding] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);
  const pollRef = useRef<number | null>(null);
  const genSeconds = useElapsed(generating);

  // LinkedIn
  const [liStatus, setLiStatus] = useState<LinkedInStatus | null>(null);
  const [liProfileUrl, setLiProfileUrl] = useState("");
  const [liQueue, setLiQueue] = usePersistentState<LiQueueItem[]>("ca.liQueue", []);
  const [liSends, setLiSends] = useState<LinkedInLogOut[]>([]);
  const liPollRef = useRef<number | null>(null);

  const smtpReady = !!status?.smtp_configured;

  useEffect(() => {
    api.tailorings().then(setTailorings).catch(() => {});
    api.health().then((h) => setPaused(h.automation_paused)).catch(() => {});
    loadSends();
    api.linkedinStatus().then(setLiStatus).catch(() => {});
    loadLiSends();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (liPollRef.current) window.clearInterval(liPollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Arriving from Jobs (a posting) or Resume (a fresh tailoring).
  useEffect(() => {
    const state = location.state as { job?: JobOut | null; tailoringId?: number } | null;
    if (!state) return;
    if (state.job) {
      const j = state.job;
      setJob(j);
      setForm((f) => ({
        ...f,
        company: j.company || "",
        role: j.title || "",
        recruiter_name: j.recruiter_name || "",
        recruiter_email: j.recruiter_email || "",
      }));
      setMessages([]);
      setCandidates([]);
    }
    if (state.tailoringId) selectResume(state.tailoringId);
    nav(location.pathname, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  // Fill name/highlights from the attached resume when they are still empty.
  useEffect(() => {
    if (attachId && !form.candidate_name && !form.highlights) selectResume(attachId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectResume(id: number | null) {
    setAttachId(id);
    if (!id) return;
    try {
      const prof = await api.profile(id);
      setForm((f) => ({
        ...f,
        candidate_name: prof.candidate_name || f.candidate_name,
        highlights: prof.highlights.length ? prof.highlights.join("\n") : f.highlights,
      }));
    } catch {
      /* resume may have been deleted; keep the manual fields */
    }
  }

  async function loadSends() {
    try {
      const rows = await api.sends(25);
      setSends(rows);
      if (pollRef.current && !rows.some((r) => r.status === "pending")) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {
      /* status table is best effort */
    }
  }

  async function loadLiSends() {
    try {
      const rows = await api.linkedinSends(25);
      setLiSends(rows);
      if (liPollRef.current && !rows.some((r) => r.status === "pending")) {
        window.clearInterval(liPollRef.current);
        liPollRef.current = null;
      }
    } catch {
      /* best effort */
    }
  }

  async function generate() {
    setGenerating(true);
    try {
      const res = await api.generateMessages({
        recruiter_name: form.recruiter_name || null,
        company: form.company,
        role: form.role,
        channel: form.channel,
        candidate_name: form.candidate_name || null,
        candidate_highlights: form.highlights.split("\n").map((s) => s.trim()).filter(Boolean),
        tone: form.tone,
        variants: Number(form.variants),
        job_id: job?.id,
        tailoring_id: attachId ?? undefined,
      });
      setMessages(res.messages);
      if (res.warning) toast.warn(res.warning);
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setGenerating(false);
    }
  }

  function editMessage(i: number, patch: Partial<GeneratedMessage>) {
    setMessages(messages.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  }

  async function copy(m: GeneratedMessage) {
    const text = m.subject ? `Subject: ${m.subject}\n\n${m.body}` : m.body;
    try {
      await navigator.clipboard.writeText(text);
      toast.ok("Copied to clipboard.");
    } catch {
      toast.err("Clipboard not available in this browser.");
    }
  }

  async function addToQueue(m: GeneratedMessage) {
    const to = form.recruiter_email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)) {
      toast.err("Add a valid recruiter email first (or use Find).");
      return;
    }
    if (queue.some((q) => q.to_email.toLowerCase() === to.toLowerCase())) {
      toast.warn(`${to} is already in the queue.`);
      return;
    }
    try {
      const history = await api.contacted(to);
      if (history.count) {
        toast.warn(
          `You already emailed ${to}${history.last_sent_at ? ` on ${formatDate(history.last_sent_at)}` : ""}. ` +
            "It will be skipped unless you tick Allow repeats."
        );
      }
    } catch {
      /* history is advisory; the server re-checks on send */
    }
    setQueue([
      ...queue,
      {
        to_email: to,
        subject: m.subject || `${form.role} at ${form.company}`,
        body: m.body,
        recruiter_name: form.recruiter_name || undefined,
        company: form.company,
        role: form.role,
        tailoring_id: attachId ?? undefined,
        job_id: job?.id || undefined,
      },
    ]);
    toast.ok(`Queued for ${to}.`);
  }

  async function send() {
    if (!queue.length) return;
    setSending(true);
    try {
      const testOnly = dryRun || !smtpReady;
      const res = await api.sendBatch(queue, testOnly, allowRepeat);
      const skipped = res.results.filter((r) => r.status === "skipped");
      if (skipped.length) {
        toast.warn(
          `Skipped ${skipped.map((s) => `${s.to_email} (${s.error})`).join(", ")}. Tick Allow repeats to send anyway.`
        );
      }
      if (testOnly) {
        const ok = res.results.length - skipped.length;
        toast.ok(`Test run: ${ok} email(s) look valid. Nothing was sent.`);
      } else {
        const later = res.results.filter((r) => r.status === "scheduled").length;
        if (res.queued - later) toast.ok(`Queued ${res.queued - later} email(s); the worker sends them, paced. Watch the status below.`);
        if (later) toast.warn(`${later} email(s) are over today's limit and will go out tomorrow morning.`);
        // Keep skipped ones queued so they can be re-sent with Allow repeats.
        const skippedTo = new Set(skipped.map((s) => s.to_email.toLowerCase()));
        setQueue(queue.filter((q) => skippedTo.has(q.to_email.toLowerCase())));
        loadSends();
        if (!pollRef.current) pollRef.current = window.setInterval(loadSends, 3000);
      }
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setSending(false);
    }
  }

  async function findEmail() {
    setFinding(true);
    setCandidates([]);
    try {
      const res = await api.findEmail({
        company: form.company,
        name: form.recruiter_name || undefined,
        job_url: job?.url || undefined,
        job_id: job?.id,
      });
      setCandidates(res.candidates);
      if (res.best) {
        setForm((f) => ({ ...f, recruiter_email: res.best!.email }));
        toast.ok(`Found ${res.candidates.length} address(es). Using the best: ${res.best.email}`);
      } else {
        toast.warn(`No email found for ${form.company}.`);
      }
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setFinding(false);
    }
  }

  function addToLiQueue(m: GeneratedMessage) {
    if (!/linkedin\.com\/in\//.test(liProfileUrl)) {
      toast.err("Enter the recruiter's LinkedIn profile URL (…linkedin.com/in/handle) first.");
      return;
    }
    setLiQueue([...liQueue, { profile_url: liProfileUrl.trim(), message: m.body, recipient_name: form.recruiter_name }]);
    toast.ok("Added to the LinkedIn queue.");
  }

  async function sendLinkedIn() {
    try {
      const res = await api.linkedinSend(liQueue, false);
      toast.ok(`Sending ${res.queued} LinkedIn DM(s)…`);
      setLiQueue([]);
      loadLiSends();
      if (!liPollRef.current) liPollRef.current = window.setInterval(loadLiSends, 4000);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  async function connectLinkedIn() {
    try {
      const res = await api.linkedinLogin();
      toast.info(res.detail);
      window.setTimeout(() => api.linkedinStatus().then(setLiStatus).catch(() => {}), 20000);
    } catch (e) {
      toast.err(errorMessage(e));
    }
  }

  const upd = (k: keyof typeof EMPTY_FORM, v: string | number) => setForm({ ...form, [k]: v });
  const canGenerate = !!form.company.trim() && !!form.role.trim();
  const liReady = !!(liStatus?.enabled && liStatus.playwright_available);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Outreach</h1>
          <p className="subtitle">
            Personalized cold emails and LinkedIn notes, grounded in the job post and your resume, sent
            from your own email account.
          </p>
        </div>
        {(form.company || messages.length > 0) && (
          <button
            className="ghost sm"
            onClick={() => {
              setForm({ ...EMPTY_FORM, candidate_name: form.candidate_name, highlights: form.highlights });
              setJob(null);
              setMessages([]);
              setCandidates([]);
            }}
          >
            Start over
          </button>
        )}
      </div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        {/* ---------- Recipient ---------- */}
        <div className="card">
          <div className="step-title" style={{ marginBottom: 14 }}>
            <span className="step-num">1</span>
            <h2 style={{ margin: 0 }}>Who you're writing to</h2>
          </div>
          {job && (
            <div className="callout" style={{ alignItems: "center" }}>
              <Icon name="jobs" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="truncate">
                  <strong>{job.title}</strong> at {job.company}
                </div>
                <div className="hint">The job post is used to personalize the message.</div>
              </div>
              <button className="ghost sm" onClick={() => setJob(null)}>
                Remove
              </button>
            </div>
          )}
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="field">
              <label htmlFor="company">Company *</label>
              <input id="company" value={form.company} onChange={(e) => upd("company", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="orole">Role *</label>
              <input id="orole" value={form.role} onChange={(e) => upd("role", e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="rname">Recruiter name</label>
            <input id="rname" value={form.recruiter_name} onChange={(e) => upd("recruiter_name", e.target.value)} placeholder="Optional; a polite greeting is used otherwise" />
          </div>
          <div className="field" style={{ marginBottom: candidates.length ? 8 : 0 }}>
            <label htmlFor="remail">Recruiter email</label>
            <div className="inline" style={{ flexWrap: "nowrap" }}>
              <input id="remail" type="email" value={form.recruiter_email} onChange={(e) => upd("recruiter_email", e.target.value)} placeholder="name@company.com" />
              <button className="secondary" onClick={findEmail} disabled={finding || !form.company.trim()} title="Search the company's website for contact emails">
                {finding ? <Spinner /> : <Icon name="search" size={16} />}
                Find
              </button>
            </div>
          </div>
          {candidates.length > 0 && (
            <div className="pills" style={{ marginTop: 4 }}>
              {candidates.map((c) => (
                <button
                  key={c.email}
                  className="secondary sm"
                  style={{ borderColor: form.recruiter_email === c.email ? "var(--accent)" : undefined }}
                  onClick={() => upd("recruiter_email", c.email)}
                  title={`Found via ${c.source}, confidence ${Math.round(c.confidence * 100)}%`}
                >
                  {c.email}
                  <span className={`badge ${c.verified === "verified" ? "ok" : c.verified === "mx_only" ? "warn" : "bad"}`}>
                    {c.verified === "mx_only" ? "domain ok" : c.verified}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ---------- About you ---------- */}
        <div className="card">
          <div className="step-title" style={{ marginBottom: 14 }}>
            <span className="step-num">2</span>
            <h2 style={{ margin: 0 }}>About you</h2>
          </div>
          <div className="field">
            <label htmlFor="attach">Attach resume</label>
            <select id="attach" value={attachId ?? ""} onChange={(e) => selectResume(e.target.value ? Number(e.target.value) : null)}>
              <option value="">No attachment</option>
              {tailorings.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.role_label}
                  {t.job_snippet ? ` · ${t.job_snippet.slice(0, 40)}` : ""} · score {Math.round(t.ats_score ?? 0)} · {formatDate(t.created_at)}
                </option>
              ))}
            </select>
            {tailorings.length === 0 && (
              <span className="hint">
                <Link to="/resume">Optimize your resume</Link> first to attach it and auto-fill this section.
              </span>
            )}
          </div>
          <div className="field">
            <label htmlFor="cname">Your name</label>
            <input id="cname" value={form.candidate_name} onChange={(e) => upd("candidate_name", e.target.value)} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="hl">Highlights to mention (one per line)</label>
            <textarea id="hl" value={form.highlights} onChange={(e) => upd("highlights", e.target.value)} placeholder="Filled from your resume when you attach one" />
          </div>
        </div>
      </div>

      {/* ---------- Generate ---------- */}
      <div className="card">
        <div className="row">
          <div className="field" style={{ flex: "0 0 auto" }}>
            <span className="label">Channel</span>
            <div className="tabs" role="tablist">
              {[
                ["email", "Email"],
                ["linkedin", "LinkedIn note"],
              ].map(([v, l]) => (
                <button key={v} role="tab" aria-selected={form.channel === v} className={form.channel === v ? "active" : ""} onClick={() => upd("channel", v)}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <label htmlFor="tone">Tone</label>
            <select id="tone" value={form.tone} onChange={(e) => upd("tone", e.target.value)}>
              <option value="professional">Professional</option>
              <option value="warm">Warm</option>
              <option value="concise">Concise</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="variants">Variants</label>
            <select id="variants" value={form.variants} onChange={(e) => upd("variants", Number(e.target.value))}>
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <button className="lg" onClick={generate} disabled={!canGenerate || generating}>
            {generating ? <Spinner /> : <Icon name="sparkle" />}
            {generating ? `Writing… ${genSeconds}s` : messages.length ? "Regenerate" : "Generate"}
          </button>
        </div>
        {!canGenerate && <div className="hint" style={{ marginTop: 8 }}>Company and role are required.</div>}
      </div>

      {messages.map((m, i) => (
        <div className="variant" key={i}>
          <div className="spread" style={{ marginBottom: 10 }}>
            <strong>
              Variant {i + 1} <span className="badge">{m.channel === "linkedin" ? "LinkedIn" : "Email"}</span>
            </strong>
            <span className="hint">{m.body.trim().split(/\s+/).length} words · editable</span>
          </div>
          {m.channel === "email" && (
            <div className="field">
              <label>Subject</label>
              <input value={m.subject || ""} onChange={(e) => editMessage(i, { subject: e.target.value })} />
            </div>
          )}
          <div className="field">
            <label>Message</label>
            <textarea value={m.body} onChange={(e) => editMessage(i, { body: e.target.value })} />
          </div>
          <div className="inline">
            {m.channel === "email" ? (
              <button className="sm" onClick={() => addToQueue(m)}>
                <Icon name="mail" size={15} /> Add to send queue
              </button>
            ) : (
              <button className="sm" onClick={() => addToLiQueue(m)} disabled={!liReady} title={liReady ? "" : "LinkedIn sending is not enabled; copy the note instead"}>
                Add to LinkedIn queue
              </button>
            )}
            <button className="secondary sm" onClick={() => copy(m)}>
              <Icon name="copy" size={15} /> Copy
            </button>
          </div>
        </div>
      ))}

      {/* ---------- Send ---------- */}
      <div className="grid-2" style={{ alignItems: "start", marginTop: messages.length ? 16 : 0 }}>
        <div className="card">
          <div className="card-header">
            <h2>Send queue ({queue.length})</h2>
            {queue.length > 0 && (
              <button className="ghost sm" onClick={() => setQueue([])}>
                Clear
              </button>
            )}
          </div>
          {paused && (
            <div className="callout warn">
              <span>
                Sending is paused. Emails stay queued until you resume them on the <Link to="/system">System</Link> page.
              </span>
            </div>
          )}
          {!smtpReady && (
            <div className="callout warn">
              <span>
                Email sending isn't set up yet, so only test runs are possible. Add your Gmail address and App Password
                in <code>~/.career-agent/.env</code> (see <Link to="/settings">Settings</Link>).
              </span>
            </div>
          )}
          {queue.length === 0 ? (
            <p className="muted small" style={{ margin: 0 }}>Generate a message and click "Add to send queue".</p>
          ) : (
            queue.map((q, i) => (
              <div className="queue-item" key={i}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="truncate">
                    <strong>{q.to_email}</strong>
                  </div>
                  <div className="hint truncate">
                    {q.subject}
                    {q.tailoring_id ? " · resume attached" : ""}
                  </div>
                </div>
                <button className="icon-btn" onClick={() => setQueue(queue.filter((_, j) => j !== i))} aria-label="Remove">
                  <Icon name="x" size={16} />
                </button>
              </div>
            ))
          )}
          <div className="spread" style={{ marginTop: 14 }}>
            <label className="check">
              <input type="checkbox" checked={dryRun || !smtpReady} disabled={!smtpReady} onChange={(e) => setDryRun(e.target.checked)} />
              Test run (validate only, don't send)
            </label>
            <label className="check" title="Send even to recruiters you have already emailed">
              <input type="checkbox" checked={allowRepeat} onChange={(e) => setAllowRepeat(e.target.checked)} />
              Allow repeats
            </label>
            <button onClick={send} disabled={!queue.length || sending}>
              {sending ? <Spinner /> : <Icon name="outreach" size={16} />}
              {dryRun || !smtpReady ? "Run test" : `Send ${queue.length}`}
            </button>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>Sent</h2>
            <button className="ghost sm" onClick={loadSends}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
          {sends.length === 0 ? (
            <EmptyState title="Nothing sent yet" />
          ) : (
            <div className="table-wrap">
              <table>
                <tbody>
                  {sends.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <div className="truncate" style={{ maxWidth: 260 }}>{s.to_email}</div>
                        <div className="hint truncate" style={{ maxWidth: 260 }}>{s.error || s.subject}</div>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <span className={`badge ${statusBadge(s.status)}`}>{s.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ---------- LinkedIn ---------- */}
      <details className="card" open={liReady}>
        <summary>LinkedIn DM sending {liReady ? "" : "(off)"}</summary>
        <div style={{ marginTop: 14 }}>
          <p className="muted small" style={{ marginTop: 0 }}>
            Sends real DMs through your own logged-in LinkedIn session. Automating LinkedIn can violate its Terms of
            Service, so keep volume low. When this is off, use Copy on a LinkedIn note instead.
          </p>
          <div className="inline" style={{ marginBottom: 12 }}>
            <span className={`badge ${liStatus?.playwright_available ? "ok" : "bad"}`}>
              {liStatus?.playwright_available ? "Browser automation available" : "Playwright not installed"}
            </span>
            <span className={`badge ${liStatus?.enabled ? "ok" : "bad"}`}>
              {liStatus?.enabled ? "Enabled" : "Disabled (CAREER_LINKEDIN__ENABLED)"}
            </span>
            <span className={`badge ${liStatus?.logged_in ? "ok" : ""}`}>{liStatus?.logged_in ? "Logged in" : "Not logged in"}</span>
          </div>
          {liReady && (
            <>
              <div className="row" style={{ marginBottom: 12 }}>
                <div className="field">
                  <label htmlFor="li">Recruiter profile URL</label>
                  <input id="li" value={liProfileUrl} onChange={(e) => setLiProfileUrl(e.target.value)} placeholder="https://www.linkedin.com/in/their-handle" />
                </div>
                <button className="secondary" onClick={connectLinkedIn}>
                  Connect LinkedIn
                </button>
              </div>
              <div className="spread">
                <span className="muted small">{liQueue.length} DM(s) queued</span>
                <button onClick={sendLinkedIn} disabled={!liQueue.length}>
                  Send LinkedIn DMs
                </button>
              </div>
              {liSends.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <tbody>
                      {liSends.map((s) => (
                        <tr key={s.id}>
                          <td>{s.recipient_name || s.profile_url}</td>
                          <td className="muted small">{s.error}</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={`badge ${statusBadge(s.status)}`}>{s.status}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </details>
    </div>
  );
}
