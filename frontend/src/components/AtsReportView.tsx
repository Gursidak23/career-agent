import type { AtsReport } from "../api/client";
import { ScoreGauge, scoreTone } from "./ui";

export default function AtsReportView({
  report,
  baseline,
}: {
  report: AtsReport;
  baseline?: number | null;
}) {
  const delta = baseline != null ? report.score - baseline : null;
  return (
    <div className="card">
      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="score-delta">
          <ScoreGauge score={report.score} label="ATS score" />
          <div className="stack" style={{ gap: 6 }}>
            {delta != null && (
              <div className="inline">
                <span className="muted">Before: {Math.round(baseline!)}</span>
                <span className={`delta ${delta < 0 ? "neg" : ""}`}>
                  {delta >= 0 ? "+" : ""}
                  {delta.toFixed(1)}
                </span>
              </div>
            )}
            <div className="muted small">
              {report.score >= 90
                ? "Strong match. Ready to send."
                : report.score >= 70
                ? "Good. The suggestions below can push it over 90."
                : "Needs work. See the suggestions below."}
            </div>
          </div>
        </div>
        <div>
          {report.components.map((c) => {
            const pct = c.max ? (c.score / c.max) * 100 : 0;
            return (
              <div className="meter" key={c.name} title={c.detail}>
                <div className="meter-head">
                  <span>{c.name}</span>
                  <span className="muted">
                    {c.score.toFixed(1)} / {c.max}
                  </span>
                </div>
                <div className={`bar ${scoreTone(pct)}`}>
                  <div style={{ width: `${pct}%` }} />
                </div>
                <div className="hint" style={{ marginTop: 3 }}>
                  {c.detail}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {(report.matched_keywords.length > 0 || report.missing_keywords.length > 0) && (
        <div className="grid-2" style={{ marginTop: 18 }}>
          <div>
            <div className="label" style={{ marginBottom: 8 }}>
              Keywords you have ({report.matched_keywords.length})
            </div>
            <div className="pills">
              {report.matched_keywords.map((k) => (
                <span className="pill hit" key={k}>
                  {k}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="label" style={{ marginBottom: 8 }}>
              Missing ({report.missing_keywords.length}). Add only if true for you.
            </div>
            <div className="pills">
              {report.missing_keywords.slice(0, 30).map((k) => (
                <span className="pill miss" key={k}>
                  {k}
                </span>
              ))}
              {report.missing_keywords.length === 0 && <span className="muted small">None</span>}
            </div>
          </div>
        </div>
      )}

      {report.suggestions.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div className="label" style={{ marginBottom: 6 }}>
            Suggestions
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {report.suggestions.map((s, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
