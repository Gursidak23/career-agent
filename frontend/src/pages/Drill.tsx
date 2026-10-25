import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  errorMessage,
  type DrillGrade,
  type DrillQuestion,
  type TailoringSummary,
} from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, Icon, Spinner } from "../components/ui";
import { formatDate, usePersistentState } from "../lib/hooks";

interface Session {
  resumeId: number;
  tailoringId: number | null;
  questions: DrillQuestion[];
  answers: string[];
  grades: (DrillGrade | null)[];
  index: number;
}

const VERDICT: Record<DrillGrade["verdict"], string> = {
  defended: "Defended",
  shaky: "Shaky",
  undefended: "Not defended",
};

export default function Drill() {
  const toast = useToast();
  const [resumeId] = usePersistentState<number | null>("ca.resumeId", null);
  const [session, setSession] = usePersistentState<Session | null>("ca.drill", null);
  const [versions, setVersions] = useState<TailoringSummary[]>([]);
  const [version, setVersion] = useState<number | "">("");
  const [count, setCount] = useState(6);
  const [starting, setStarting] = useState(false);
  const [grading, setGrading] = useState(false);

  useEffect(() => {
    if (resumeId) api.tailorings(resumeId).then(setVersions).catch(() => {});
  }, [resumeId]);

  async function start() {
    if (!resumeId) return;
    setStarting(true);
    try {
      const questions = await api.drillQuestions({
        resume_id: resumeId,
        tailoring_id: version || undefined,
        count,
      });
      if (!questions.length) {
        toast.warn("No claims to question in this version.");
        return;
      }
      setSession({
        resumeId,
        tailoringId: version || null,
        questions,
        answers: questions.map(() => ""),
        grades: questions.map(() => null),
        index: 0,
      });
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setStarting(false);
    }
  }

  function update(patch: Partial<Session>) {
    setSession((s) => (s ? { ...s, ...patch } : s));
  }

  async function grade() {
    if (!session) return;
    const q = session.questions[session.index];
    setGrading(true);
    try {
      const g = await api.drillGrade({
        claim: q.claim,
        question: q.question,
        look_for: q.look_for,
        answer: session.answers[session.index],
      });
      update({ grades: session.grades.map((x, i) => (i === session.index ? g : x)) });
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setGrading(false);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.ok("Copied. Paste it into your resume.");
    } catch {
      toast.err("Clipboard not available.");
    }
  }

  if (!resumeId) {
    return (
      <div>
        <h1>Interview drill</h1>
        <div className="card">
          <EmptyState icon={<Icon name="resume" />} title="No resume yet">
            <Link to="/resume">Upload your resume</Link> first.
          </EmptyState>
        </div>
      </div>
    );
  }

  const done = session ? session.grades.filter(Boolean).length : 0;
  const finished = session && done === session.questions.length;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Interview drill</h1>
          <p className="subtitle">
            A skeptical interviewer questions the claims on your resume, numbers first. Answer as you would out loud;
            anything you can't back up gets safer wording.
          </p>
        </div>
        {session && (
          <button className="ghost sm" onClick={() => setSession(null)}>
            New drill
          </button>
        )}
      </div>

      {!session && (
        <div className="card">
          <div className="row">
            <div className="field" style={{ flex: "2 1 260px" }}>
              <label htmlFor="d-version">Resume version</label>
              <select id="d-version" value={version} onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Original resume</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.role_label}
                    {v.job_snippet ? ` · ${v.job_snippet.slice(0, 40)}` : ""} · {formatDate(v.created_at)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="d-count">Questions</label>
              <select id="d-count" value={count} onChange={(e) => setCount(Number(e.target.value))}>
                {[4, 6, 8, 10].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </div>
            <button className="lg" onClick={start} disabled={starting}>
              {starting ? <Spinner /> : <Icon name="sparkle" />}
              {starting ? "Preparing questions…" : "Start drill"}
            </button>
          </div>
        </div>
      )}

      {session && (
        <>
          <div className="card">
            <div className="spread" style={{ marginBottom: 10 }}>
              <span className="muted small">
                {done} of {session.questions.length} answered
              </span>
              <div className="dots" aria-label="Progress">
                {session.questions.map((_, i) => (
                  <button
                    key={i}
                    className="ghost"
                    style={{ padding: 2 }}
                    onClick={() => update({ index: i })}
                    aria-label={`Question ${i + 1}`}
                  >
                    <span
                      className={`${session.grades[i]?.verdict ?? ""} ${i === session.index ? "current" : ""}`}
                      style={{ display: "block", width: 26, height: 6, borderRadius: 4 }}
                    />
                  </button>
                ))}
              </div>
            </div>

            {(() => {
              const q = session.questions[session.index];
              const g = session.grades[session.index];
              return (
                <>
                  <div className="hint" style={{ marginBottom: 6 }}>
                    Question {session.index + 1} · {q.where}
                  </div>
                  <div className="drill-claim">{q.claim}</div>
                  <div className="drill-question">{q.question}</div>
                  <textarea
                    value={session.answers[session.index]}
                    onChange={(e) =>
                      update({ answers: session.answers.map((a, i) => (i === session.index ? e.target.value : a)) })
                    }
                    placeholder="Your answer: what you did, how you measured it, your own role, the trade-offs…"
                    style={{ minHeight: 140 }}
                    aria-label="Your answer"
                  />
                  <div className="spread" style={{ marginTop: 10 }}>
                    <details>
                      <summary className="small">What a strong answer covers</summary>
                      <ul className="issues">
                        {q.look_for.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    </details>
                    <button onClick={grade} disabled={grading || !session.answers[session.index].trim()}>
                      {grading ? <Spinner /> : null}
                      {g ? "Grade again" : "Grade my answer"}
                    </button>
                  </div>

                  {g && (
                    <div className={`grade ${g.verdict}`}>
                      <div className="inline" style={{ marginBottom: 6 }}>
                        <strong>{VERDICT[g.verdict]}</strong>
                        <span className="muted small">{g.score}/5</span>
                      </div>
                      <div>{g.feedback}</div>
                      {g.follow_up && (
                        <div style={{ marginTop: 8 }}>
                          <span className="label">Likely follow-up: </span>
                          {g.follow_up}
                        </div>
                      )}
                      {g.safer_wording && (
                        <div style={{ marginTop: 10 }}>
                          <div className="label">Safer wording you can defend</div>
                          <div className="spread" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
                            <span style={{ flex: 1 }}>{g.safer_wording}</span>
                            <button className="secondary sm" onClick={() => copy(g.safer_wording!)}>
                              <Icon name="copy" size={14} /> Copy
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="spread" style={{ marginTop: 14 }}>
                    <button
                      className="secondary sm"
                      onClick={() => update({ index: session.index - 1 })}
                      disabled={session.index === 0}
                    >
                      Previous
                    </button>
                    <button
                      className="secondary sm"
                      onClick={() => update({ index: session.index + 1 })}
                      disabled={session.index === session.questions.length - 1}
                    >
                      Next <Icon name="arrow" size={14} />
                    </button>
                  </div>
                </>
              );
            })()}
          </div>

          {finished && (
            <div className="card">
              <h2>Summary</h2>
              <div className="inline" style={{ marginBottom: 12 }}>
                {(["defended", "shaky", "undefended"] as const).map((v) => (
                  <span key={v} className={`badge ${v === "defended" ? "ok" : v === "shaky" ? "warn" : "bad"}`}>
                    {session.grades.filter((g) => g?.verdict === v).length} {VERDICT[v].toLowerCase()}
                  </span>
                ))}
              </div>
              {session.questions.map((q, i) => {
                const g = session.grades[i];
                if (!g || g.verdict === "defended") return null;
                return (
                  <div key={i} className="requirement">
                    <div className="hint">{q.where}</div>
                    <div className="was" style={{ textDecoration: "none" }}>{q.claim}</div>
                    {g.safer_wording ? (
                      <div className="spread" style={{ flexWrap: "nowrap", alignItems: "flex-start", marginTop: 6 }}>
                        <span style={{ flex: 1 }}>
                          <span className="label">Safer: </span>
                          {g.safer_wording}
                        </span>
                        <button className="secondary sm" onClick={() => copy(g.safer_wording!)}>
                          <Icon name="copy" size={14} />
                        </button>
                      </div>
                    ) : (
                      <div className="hint" style={{ marginTop: 6 }}>Prepare a clearer answer: {g.feedback}</div>
                    )}
                  </div>
                );
              })}
              {session.grades.every((g) => g?.verdict === "defended") && (
                <p className="muted" style={{ margin: 0 }}>Every claim held up. You're ready for this resume.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
