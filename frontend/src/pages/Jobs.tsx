import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, type JobOut } from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";
import { useDebounced, usePersistentState } from "../lib/hooks";

const pretty = (s?: string | null) =>
  s ? s.replace(/_/g, "-").replace(/^\w/, (c) => c.toUpperCase()) : "";

const SOURCE_HINTS: Record<string, string> = {
  all: "All free sources combined",
  remotive: "Remote tech jobs",
  remoteok: "Remote jobs with salaries",
  arbeitnow: "EU and remote jobs",
  hackernews: "HN Who's Hiring (often has emails)",
  apify: "Indian job boards (needs Apify token)",
  scrapy: "Custom Scrapy spider",
};

export default function Jobs() {
  const nav = useNavigate();
  const toast = useToast();
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [meta, setMeta] = useState({ sources: [] as string[], job_types: [] as string[], experience_levels: [] as string[] });
  const [filters, setFilters] = usePersistentState("ca.jobFilters", {
    job_type: "",
    experience: "",
    location: "",
    search: "",
    has_email: "",
  });
  const [source, setSource] = usePersistentState("ca.jobSource", "all");
  const [enrich, setEnrich] = usePersistentState("ca.jobEnrich", false);
  const [fetching, setFetching] = useState(false);
  const [finding, setFinding] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const pollRef = useRef<number | null>(null);

  const debouncedFilters = useDebounced(filters, 300);

  useEffect(() => {
    api.jobsMeta().then(setMeta).catch((e) => toast.err(errorMessage(e)));
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFilters]);

  async function load() {
    const params: Record<string, string> = {};
    Object.entries(filters).forEach(([k, v]) => v && (params[k] = v));
    try {
      setJobs(await api.listJobs(params));
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setLoaded(true);
    }
  }

  async function fetchNew() {
    setFetching(true);
    try {
      const fetched = await api.refreshJobs({
        source,
        query: filters.search || undefined,
        location: filters.location || undefined,
        limit: 25,
        enrich_emails: enrich,
      });
      toast.ok(`Fetched ${fetched.length} job${fetched.length === 1 ? "" : "s"} from ${source}.`);
      await load();
      if (enrich) {
        // Email enrichment runs in the background: re-check a few times.
        let polls = 0;
        if (pollRef.current) window.clearInterval(pollRef.current);
        pollRef.current = window.setInterval(() => {
          load();
          if (++polls >= 6 && pollRef.current) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, 5000);
        toast.info("Looking for recruiter emails in the background…");
      }
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setFetching(false);
    }
  }

  async function findEmail(job: JobOut) {
    setFinding(job.id);
    try {
      const res = await api.findEmail({
        company: job.company,
        name: job.recruiter_name || undefined,
        job_url: job.url || undefined,
        job_id: job.id,
      });
      if (res.best) {
        setJobs((prev) => prev.map((j) => (j.id === job.id ? { ...j, recruiter_email: res.best!.email } : j)));
        toast.ok(`Found ${res.best.email} (${res.best.verified}).`);
      } else {
        toast.warn(`No email found for ${job.company}.`);
      }
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setFinding(null);
    }
  }

  const set = (k: keyof typeof filters, v: string) => setFilters({ ...filters, [k]: v });
  const anyFilter = Object.values(filters).some(Boolean);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Jobs</h1>
          <p className="subtitle">
            Live postings from free job boards. Tailor your resume to one, then draft outreach to its recruiter.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="row">
          <div className="field" style={{ flex: "2 1 220px" }}>
            <label htmlFor="source">Fetch new jobs from</label>
            <select id="source" value={source} onChange={(e) => setSource(e.target.value)}>
              {meta.sources.map((s) => (
                <option key={s} value={s}>
                  {s}: {SOURCE_HINTS[s] ?? ""}
                </option>
              ))}
            </select>
          </div>
          <label className="check" style={{ paddingBottom: 9 }} title="Runs the email finder on new postings without a recruiter email">
            <input type="checkbox" checked={enrich} onChange={(e) => setEnrich(e.target.checked)} />
            Also find recruiter emails
          </label>
          <button onClick={fetchNew} disabled={fetching}>
            {fetching ? <Spinner /> : <Icon name="refresh" size={16} />}
            {fetching ? "Fetching…" : "Fetch jobs"}
          </button>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>
          Your search and location below are also sent to the source.
        </div>
      </div>

      <div className="card">
        <div className="toolbar">
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="search">Search</label>
            <div className="input-icon">
              <Icon name="search" size={16} />
              <input
                id="search"
                value={filters.search}
                onChange={(e) => set("search", e.target.value)}
                placeholder="Title or description, e.g. backend, Python"
              />
            </div>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="loc">Location</label>
            <input id="loc" value={filters.location} onChange={(e) => set("location", e.target.value)} placeholder="Remote, Berlin…" />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="type">Type</label>
            <select id="type" value={filters.job_type} onChange={(e) => set("job_type", e.target.value)}>
              <option value="">Any</option>
              {meta.job_types.map((t) => (
                <option key={t} value={t}>
                  {pretty(t)}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="exp">Experience</label>
            <select id="exp" value={filters.experience} onChange={(e) => set("experience", e.target.value)}>
              <option value="">Any</option>
              {meta.experience_levels.map((t) => (
                <option key={t} value={t}>
                  {pretty(t)}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="email">Recruiter email</label>
            <select id="email" value={filters.has_email} onChange={(e) => set("has_email", e.target.value)}>
              <option value="">Any</option>
              <option value="true">Has email</option>
            </select>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>
            {jobs.length} job{jobs.length === 1 ? "" : "s"}
            {anyFilter && <span className="muted" style={{ fontWeight: 400 }}> matching filters</span>}
          </h2>
          {anyFilter && (
            <button
              className="ghost sm"
              onClick={() => setFilters({ job_type: "", experience: "", location: "", search: "", has_email: "" })}
            >
              Clear filters
            </button>
          )}
        </div>

        {loaded && jobs.length === 0 && (
          <EmptyState icon={<Icon name="jobs" />} title={anyFilter ? "No jobs match these filters" : "No jobs yet"}>
            {anyFilter ? "Try clearing a filter, or fetch new jobs." : "Click Fetch jobs above to pull live postings."}
          </EmptyState>
        )}

        {jobs.map((j) => (
          <div className="job" key={j.id}>
            <div className="job-top">
              <div className="job-main">
                {j.url ? (
                  <a className="job-title" href={j.url} target="_blank" rel="noreferrer">
                    {j.title} <Icon name="external" size={13} />
                  </a>
                ) : (
                  <span className="job-title">{j.title}</span>
                )}
                <div className="job-meta">
                  <strong style={{ color: "var(--text)", fontWeight: 500 }}>{j.company}</strong>
                  {j.location && <span>{j.location}</span>}
                  {j.job_type && <span className="badge">{pretty(j.job_type)}</span>}
                  {j.experience && <span className="badge">{pretty(j.experience)}</span>}
                  <span className="badge accent">{j.source}</span>
                </div>
                <div className="job-meta">
                  {j.recruiter_email ? (
                    <span className="inline" style={{ gap: 5 }}>
                      <Icon name="mail" size={14} /> {j.recruiter_email}
                    </span>
                  ) : (
                    <button className="ghost sm" style={{ padding: "2px 6px", marginLeft: -6 }} onClick={() => findEmail(j)} disabled={finding === j.id}>
                      {finding === j.id ? <Spinner size={12} /> : <Icon name="search" size={14} />}
                      {finding === j.id ? "Searching company site…" : "Find recruiter email"}
                    </button>
                  )}
                  {j.description && (
                    <button className="ghost sm" style={{ padding: "2px 6px" }} onClick={() => setExpanded(expanded === j.id ? null : j.id)} aria-expanded={expanded === j.id}>
                      {expanded === j.id ? "Hide description" : "Show description"}
                    </button>
                  )}
                </div>
              </div>
              <div className="job-actions">
                <button className="secondary sm" onClick={() => nav("/resume", { state: { job: j } })} title="Tailor your resume to this job's description">
                  <Icon name="sparkle" size={15} /> Tailor resume
                </button>
                <button className="secondary sm" onClick={() => nav("/outreach", { state: { job: j } })}>
                  <Icon name="outreach" size={15} /> Draft outreach
                </button>
              </div>
            </div>
            {expanded === j.id && j.description && <div className="job-desc">{j.description}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
