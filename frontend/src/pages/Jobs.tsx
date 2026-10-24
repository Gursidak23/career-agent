import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, type JobOut, type ResumeSummary } from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";
import { formatDate, titleCase, useDebounced, usePersistentState } from "../lib/hooks";

// Read once per visit: jobs added after this are flagged "New".
function useLastVisit(key: string): number {
  const [previous] = useState(() => {
    try {
      return Number(localStorage.getItem(key) || 0);
    } catch {
      return 0;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, String(Date.now()));
    } catch {
      /* storage unavailable */
    }
  }, [key]);
  return previous;
}

const toMs = (iso?: string | null) =>
  iso ? new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime() : 0;

const matchTone = (score: number) => (score >= 60 ? "good" : score >= 35 ? "mid" : "low");

const pretty = (s?: string | null) =>
  s ? s.replace(/_/g, "-").replace(/^\w/, (c) => c.toUpperCase()) : "";

const SOURCE_HINTS: Record<string, string> = {
  all: "All free sources combined",
  remotive: "Remote tech jobs",
  remoteok: "Remote jobs with salaries",
  arbeitnow: "EU and remote jobs",
  hackernews: "HN Who's Hiring (often has emails)",
  companies: "Company career pages (Greenhouse, Lever, Ashby)",
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
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [rankWith, setRankWith] = usePersistentState<number | null>("ca.resumeId", null);
  const [sort, setSort] = usePersistentState<"match" | "newest">("ca.jobSort", "match");
  const [minMatch, setMinMatch] = usePersistentState("ca.jobMinMatch", 0);
  const [tracking, setTracking] = useState<number | null>(null);
  const lastVisit = useLastVisit("ca.jobsSeenAt");

  const debouncedFilters = useDebounced(filters, 300);

  useEffect(() => {
    api.jobsMeta().then(setMeta).catch((e) => toast.err(errorMessage(e)));
    api
      .resumes()
      .then((rows) => {
        const complete = rows.filter((r) => r.complete);
        setResumes(complete);
        if (!complete.some((r) => r.id === rankWith)) setRankWith(complete[0]?.id ?? null);
      })
      .catch(() => {});
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFilters, rankWith, sort, minMatch]);

  async function load() {
    const params: Record<string, string> = {};
    Object.entries(filters).forEach(([k, v]) => v && (params[k] = v));
    if (rankWith) {
      params.resume_id = String(rankWith);
      params.sort = sort;
      if (minMatch) params.min_match = String(minMatch);
    }
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

  async function track(job: JobOut) {
    setTracking(job.id);
    try {
      const app = await api.createApplication({ job_id: job.id });
      setJobs((prev) =>
        prev.map((j) => (j.id === job.id ? { ...j, application_id: app.id, application_status: app.status } : j))
      );
      toast.ok(`Tracking ${job.title} at ${job.company}.`);
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setTracking(null);
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
        <div className="row">
          <div className="field" style={{ flex: "2 1 220px" }}>
            <label htmlFor="rank">Rank against</label>
            <select id="rank" value={rankWith ?? ""} onChange={(e) => setRankWith(e.target.value ? Number(e.target.value) : null)}>
              <option value="">No ranking</option>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>
                  {titleCase(r.name) || r.filename} · {r.filename} · {formatDate(r.created_at)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="sort">Sort by</label>
            <select id="sort" value={sort} onChange={(e) => setSort(e.target.value as "match" | "newest")} disabled={!rankWith}>
              <option value="match">Best match</option>
              <option value="newest">Newest</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="minmatch">Match</label>
            <select id="minmatch" value={minMatch} onChange={(e) => setMinMatch(Number(e.target.value))} disabled={!rankWith}>
              <option value={0}>Any</option>
              <option value={40}>40%+</option>
              <option value={60}>60%+</option>
              <option value={80}>80%+</option>
            </select>
          </div>
        </div>
        {!resumes.length && (
          <div className="hint" style={{ marginTop: 8 }}>
            <Link to="/resume">Upload your resume</Link> to rank jobs by how well they fit you.
          </div>
        )}
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
              {j.match_score != null && (
                <span
                  className={`match ${matchTone(j.match_score)}`}
                  title={`Matches ${j.match_matched?.join(", ") || "none"}${
                    j.match_missing?.length ? `\nMissing ${j.match_missing.join(", ")}` : ""
                  }`}
                >
                  {j.match_score}%
                </span>
              )}
              <div className="job-main">
                {(j.is_new || toMs(j.created_at) > lastVisit) && lastVisit > 0 && (
                  <span className="badge new" style={{ marginRight: 8 }}>New</span>
                )}
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
                {!!j.match_missing?.length && (j.match_score ?? 0) > 0 && (
                  <div className="hint" style={{ marginTop: 4 }}>
                    Missing: {j.match_missing.slice(0, 4).join(", ")}
                    {j.match_missing.length > 4 ? ` +${j.match_missing.length - 4}` : ""}
                  </div>
                )}
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
                {j.application_status ? (
                  <Link to="/tracker" className="badge ok" style={{ alignSelf: "center" }} title="Open the tracker">
                    {j.application_status}
                  </Link>
                ) : (
                  <button className="secondary sm" onClick={() => track(j)} disabled={tracking === j.id}>
                    {tracking === j.id ? <Spinner size={12} /> : <Icon name="check" size={14} />} Track
                  </button>
                )}
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
