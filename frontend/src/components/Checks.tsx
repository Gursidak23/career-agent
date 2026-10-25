import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type AtsCheckReport,
  type CheckTarget,
  type EvidenceReport,
  type ScanReport,
} from "../api/client";
import { useToast } from "./Toast";
import { EmptyState, Icon, Spinner } from "./ui";

const VERDICT: Record<AtsCheckReport["verdict"], [string, string]> = {
  excellent: ["ok", "Excellent"],
  good: ["warn", "Good"],
  risky: ["bad", "Risky"],
};

/** ATS read-back + recruiter 6-second scan for one PDF, in two lazy tabs. */
export function QualityChecks({
  target,
  title = "Quality checks",
  onRerender,
}: {
  target: CheckTarget;
  title?: string;
  onRerender?: () => Promise<void>;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<"ats" | "scan">("ats");
  const [ats, setAts] = useState<AtsCheckReport | null>(null);
  const [scan, setScan] = useState<ScanReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const key = JSON.stringify(target);

  useEffect(() => {
    setAts(null);
    setScan(null);
    setError(null);
  }, [key, version]);

  useEffect(() => {
    if ((tab === "ats" && ats) || (tab === "scan" && scan)) return;
    let stale = false;
    setLoading(true);
    setError(null);
    (tab === "ats" ? api.atsCheck(target).then((r) => !stale && setAts(r)) : api.scan(target).then((r) => !stale && setScan(r)))
      .catch((e) => !stale && setError(errorMessage(e)))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, key, version, ats, scan]);

  const outdated = ats?.extractors.some((e) =>
    e.issues.some((i) => i.startsWith("Ligatures") || i.includes("broken apart"))
  );

  async function rerender() {
    if (!onRerender) return;
    setLoading(true);
    try {
      await onRerender();
      setVersion((v) => v + 1);
      toast.ok("Re-rendered with the latest ATS-safe template.");
    } catch (e) {
      toast.err(errorMessage(e));
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h2>{title}</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "ats"} className={tab === "ats" ? "active" : ""} onClick={() => setTab("ats")}>
            What an ATS reads
          </button>
          <button role="tab" aria-selected={tab === "scan"} className={tab === "scan" ? "active" : ""} onClick={() => setTab("scan")}>
            6-second scan
          </button>
        </div>
      </div>

      {loading && (
        <div className="muted inline">
          <Spinner /> {tab === "ats" ? "Running three PDF parsers…" : "Simulating a recruiter's first glance…"}
        </div>
      )}
      {error && !loading && <div className="callout bad">{error}</div>}

      {tab === "ats" && ats && !loading && (
        <div>
          <div className="inline" style={{ marginBottom: 12 }}>
            <span className={`badge ${VERDICT[ats.verdict][0]}`}>{VERDICT[ats.verdict][1]}</span>
            <span className="muted small">
              Worst of three parsers: {ats.score}/100. An ATS uses one of these kinds of extractor, so the weakest
              result is what counts.
            </span>
          </div>
          {outdated && onRerender && (
            <div className="callout warn" style={{ alignItems: "center" }}>
              <span style={{ flex: 1 }}>This PDF was made before the latest ATS-safety fixes (ligatures, kerning).</span>
              <button className="sm" onClick={rerender}>
                Re-render
              </button>
            </div>
          )}
          {ats.extractors.map((e) => (
            <details key={e.name} className="extractor" open={e.issues.length > 0}>
              <summary>
                <span style={{ flex: 1 }}>{e.name}</span>
                <span className="hint">
                  words {e.word_coverage}% · bullets {e.bullets_intact}%
                </span>
                <span className={`badge ${e.score >= 92 ? "ok" : e.score >= 80 ? "warn" : "bad"}`}>{e.score}</span>
              </summary>
              {e.issues.length ? (
                <ul className="issues">
                  {e.issues.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              ) : (
                <div className="hint" style={{ margin: "6px 0" }}>
                  <Icon name="check" size={13} /> Reads back cleanly.
                </div>
              )}
              <details>
                <summary className="small">Show the raw text it extracts</summary>
                <pre className="extract">{e.preview}</pre>
              </details>
            </details>
          ))}
          {ats.notes.map((n) => (
            <p key={n} className="hint" style={{ margin: "10px 0 0" }}>
              {n}
            </p>
          ))}
        </div>
      )}

      {tab === "scan" && scan && !loading && (
        <div className="scan-grid">
          <a href={api.scanImageUrl(target, String(version))} target="_blank" rel="noreferrer" title="Open full size">
            <img className="heatmap" src={api.scanImageUrl(target, String(version))} alt="Attention heatmap of the resume" />
          </a>
          <div className="stack">
            <div>
              <div className="label">Read in the first ~6 seconds ({scan.seen_words} words, boxed in red)</div>
              <blockquote className="seen">{scan.seen_text}</blockquote>
            </div>
            <div>
              <div className="label">Key skills seen at a glance</div>
              <div className="pills">
                {scan.keywords_in_view.length ? (
                  scan.keywords_in_view.map((k) => <span key={k} className="pill hit">{k}</span>)
                ) : (
                  <span className="muted small">None</span>
                )}
              </div>
            </div>
            {scan.keywords_buried.length > 0 && (
              <div>
                <div className="label">Present, but easy to miss</div>
                <div className="pills">
                  {scan.keywords_buried.map((k) => (
                    <span key={k} className="pill" style={{ color: "var(--warn)" }}>
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="muted small">
              Numbers in view: {scan.metrics_in_view} of {scan.metrics_total}
            </div>
            {scan.tips.length > 0 && (
              <ul className="issues">
                {scan.tips.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
            <div className="hint">
              A heuristic model of skimming (F-pattern, emphasis, numbers), not eye-tracking data.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const STATUS: Record<string, [string, string]> = {
  met: ["ok", "Met"],
  partial: ["warn", "Partial"],
  gap: ["bad", "Gap"],
};

/** Job requirements mapped to resume lines that prove them (or flagged as gaps). */
export function EvidencePanel({
  resumeId,
  tailoringId,
  jobDescription,
}: {
  resumeId: number;
  tailoringId?: number;
  jobDescription: string;
}) {
  const toast = useToast();
  const [report, setReport] = useState<EvidenceReport | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    try {
      setReport(await api.evidence({ resume_id: resumeId, tailoring_id: tailoringId, job_description: jobDescription }));
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  const ready = jobDescription.trim().split(/\s+/).length >= 15;

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2>Requirements vs. your evidence</h2>
          <div className="hint">Each requirement in the job post, matched to resume lines that prove it.</div>
        </div>
        <button className="secondary sm" onClick={run} disabled={!ready || loading}>
          {loading ? <Spinner /> : <Icon name="search" size={15} />}
          {report ? "Re-check" : "Check requirements"}
        </button>
      </div>
      {!ready && !report && <p className="muted small" style={{ margin: 0 }}>Paste a job description above (or pick a job) to compare it with your resume.</p>}
      {report && (
        <>
          <div className="inline" style={{ marginBottom: 12 }}>
            <span className={`badge ${report.must_met === report.must_total ? "ok" : report.must_met >= report.must_total / 2 ? "warn" : "bad"}`}>
              Must-haves {report.must_met}/{report.must_total} met
            </span>
            {report.nice_total > 0 && (
              <span className="badge">
                Nice-to-haves {report.nice_met}/{report.nice_total}
              </span>
            )}
            {report.years_required != null && (
              <span className="badge">
                Asks {report.years_required}+ yrs · you ~{report.years_candidate}
              </span>
            )}
          </div>
          {report.red_flags.map((f) => (
            <div key={f.text} className="callout warn">
              <span>
                <strong>{f.text}.</strong> {f.why}
              </span>
            </div>
          ))}
          {report.requirements.length === 0 ? (
            <EmptyState title="No requirements found in this post" />
          ) : (
            report.requirements.map((r, i) => (
              <div key={i} className="requirement">
                <div className="spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                  <strong style={{ flex: 1 }}>{r.text}</strong>
                  <span className="badge">{r.kind === "must" ? "Must" : "Nice"}</span>
                  <span className={`badge ${STATUS[r.status][0]}`}>{STATUS[r.status][1]}</span>
                </div>
                {r.evidence.map((e) => (
                  <div key={e.id} className="evidence">
                    <span className="hint">{e.where}:</span> {e.text}
                  </div>
                ))}
                {r.note && <div className="hint" style={{ marginTop: 4 }}>{r.note}</div>}
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}
