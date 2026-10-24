import { useEffect, useState } from "react";
import { api, errorMessage, type ConnectionTest, type SettingsStatus } from "../api/client";
import { useToast } from "../components/Toast";
import { Icon, Spinner } from "../components/ui";

const PROVIDER_LABELS: Record<string, string> = {
  gemini: "Google Gemini",
  groq: "Groq",
  copilot: "GitHub Copilot (paid, last resort)",
};

function Check({ ok, title, children }: { ok: boolean; title: string; children: React.ReactNode }) {
  return (
    <div className="queue-item" style={{ alignItems: "flex-start" }}>
      <span className={`step-num ${ok ? "done" : ""}`} style={ok ? undefined : { background: "var(--warn-soft)", color: "var(--warn)" }}>
        <Icon name={ok ? "check" : "x"} size={14} />
      </span>
      <div>
        <strong>{title}</strong>
        <div className="muted small">{children}</div>
      </div>
    </div>
  );
}

export default function Settings({ onStatus }: { onStatus: (s: SettingsStatus) => void }) {
  const toast = useToast();
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [llmTests, setLlmTests] = useState<Record<string, ConnectionTest>>({});
  const [smtpTest, setSmtpTest] = useState<ConnectionTest | null>(null);
  const [testingLlm, setTestingLlm] = useState(false);
  const [testingSmtp, setTestingSmtp] = useState(false);

  useEffect(() => {
    api
      .status()
      .then((s) => {
        setStatus(s);
        onStatus(s);
      })
      .catch((e) => toast.err(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function testLlm() {
    setTestingLlm(true);
    try {
      const rows = await api.testLlm();
      setLlmTests(Object.fromEntries(rows.map((r) => [r.name, r])));
      const failed = rows.filter((r) => !r.ok).length;
      if (failed) toast.warn(`${failed} provider(s) failed. See details in the table.`);
      else toast.ok("All configured AI providers responded.");
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setTestingLlm(false);
    }
  }

  async function testSmtp() {
    setTestingSmtp(true);
    try {
      setSmtpTest(await api.testSmtp());
    } catch (e) {
      toast.err(errorMessage(e));
    } finally {
      setTestingSmtp(false);
    }
  }

  if (!status) {
    return (
      <div className="card">
        <Spinner /> Loading status…
      </div>
    );
  }

  const llmReady = status.providers.some((p) => p.configured);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p className="subtitle">
            Configuration lives in <code>backend/.env</code> (restart the backend after editing). This page shows what
            is active and lets you test it.
          </p>
        </div>
      </div>

      {!!status.env_overrides?.length && (
        <div className="callout warn">
          <span>
            <strong>Your terminal is overriding backend/.env.</strong> These variables were exported in the shell that
            started the backend and differ from <code>.env</code>: {status.env_overrides.join(", ")}. Restart the
            backend from a fresh terminal (or <code>unset</code> them) so your latest settings apply.
          </span>
        </div>
      )}

      <div className="card">
        <h2>Setup checklist</h2>
        <Check ok={llmReady} title="AI provider">
          {llmReady ? "At least one LLM key is set. Use Test to confirm it actually works." : "Set CAREER_LLM__GEMINI_API_KEY (free) to enable parsing, tailoring and writing."}
        </Check>
        <Check ok={status.smtp_configured} title="Email sending">
          {status.smtp_configured
            ? "SMTP credentials are set."
            : "Set CAREER_SMTP__USERNAME, CAREER_SMTP__PASSWORD (a Gmail App Password) and CAREER_SMTP__FROM_NAME."}
        </Check>
        <Check ok={status.tectonic_available} title="PDF export">
          {status.tectonic_available ? "Tectonic is installed." : "Install Tectonic (brew install tectonic). Word (.docx) export works without it."}
        </Check>
        <Check ok title="Recruiter email finder">
          {status.email_providers.filter((p) => p.enabled).map((p) => p.name).join(", ") || "crawler, pattern"} enabled.
        </Check>
      </div>

      <div className="card">
        <div className="card-header">
          <h2>AI providers (tried in this order)</h2>
          <button className="secondary sm" onClick={testLlm} disabled={testingLlm || !llmReady}>
            {testingLlm ? <Spinner /> : <Icon name="refresh" size={15} />}
            {testingLlm ? "Testing…" : "Test connections"}
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Key</th>
                <th>Test</th>
              </tr>
            </thead>
            <tbody>
              {status.providers.map((p) => {
                const t = llmTests[p.name];
                return (
                  <tr key={p.name}>
                    <td>{PROVIDER_LABELS[p.name] ?? p.name}</td>
                    <td className="muted">{p.model}</td>
                    <td>
                      <span className={`badge ${p.configured ? "ok" : ""}`}>{p.configured ? "set" : "not set"}</span>
                    </td>
                    <td>
                      {t ? (
                        t.ok ? (
                          <span className="badge ok">ok · {((t.latency_ms ?? 0) / 1000).toFixed(1)}s</span>
                        ) : (
                          <span className="badge bad" title={t.detail}>
                            failed
                          </span>
                        )
                      ) : (
                        <span className="hint">{p.configured ? "not tested" : "skipped"}</span>
                      )}
                      {t && !t.ok && <div className="hint" style={{ maxWidth: 360, overflowWrap: "anywhere" }}>{t.detail}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginBottom: 0 }}>
          The test sends a one-word prompt to each provider. Copilot calls use your Copilot AI credits.
        </p>
      </div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="card-header">
            <h2>Email (SMTP)</h2>
            <button className="secondary sm" onClick={testSmtp} disabled={testingSmtp || !status.smtp_configured}>
              {testingSmtp ? <Spinner /> : null}
              Test login
            </button>
          </div>
          <span className={`badge ${status.smtp_configured ? "ok" : "warn"}`}>
            {status.smtp_configured ? "Configured" : "Not configured"}
          </span>
          {smtpTest && (
            <div className={`callout ${smtpTest.ok ? "ok" : "bad"}`} style={{ marginTop: 12, marginBottom: 0 }}>
              {smtpTest.ok ? `Login succeeded (${((smtpTest.latency_ms ?? 0) / 1000).toFixed(1)}s). No email was sent.` : smtpTest.detail}
            </div>
          )}
          <p className="hint" style={{ marginBottom: 0 }}>
            Schedule and digest: CAREER_SCRAPER__AUTO_REFRESH_HOURS and CAREER_SCRAPER__DIGEST_EMAIL.
            <br />
            Gmail: Google Account → Security → 2-Step Verification → App passwords.
          </p>
        </div>

        <div className="card">
          <h2>Integrations</h2>
          <div className="stack">
            <div className="spread">
              <span>Tectonic (PDF)</span>
              <span className={`badge ${status.tectonic_available ? "ok" : "warn"}`}>{status.tectonic_available ? "installed" : "missing"}</span>
            </div>
            <div className="spread">
              <span>LinkedIn DM automation</span>
              <span className={`badge ${status.linkedin_enabled && status.linkedin_available ? "ok" : ""}`}>
                {status.linkedin_available ? (status.linkedin_enabled ? "enabled" : "disabled") : "Playwright missing"}
              </span>
            </div>
            <div className="spread">
              <span>Company career boards</span>
              <span className="badge ok">{status.company_boards ?? 0} companies</span>
            </div>
            <div className="spread">
              <span>Scheduled job fetch</span>
              <span className={`badge ${status.auto_refresh_hours ? "ok" : ""}`}>
                {status.auto_refresh_hours ? `every ${status.auto_refresh_hours}h` : "off"}
              </span>
            </div>
            <div className="spread">
              <span>Daily match digest</span>
              <span className={`badge ${status.digest_email && status.smtp_configured ? "ok" : ""}`}>
                {status.digest_email ? (status.smtp_configured ? status.digest_email : "needs SMTP") : "off"}
              </span>
            </div>
            {status.email_providers.map((p) => (
              <div className="spread" key={p.name}>
                <span>Email finder: {p.name}</span>
                <span className={`badge ${p.enabled ? "ok" : ""}`}>{p.enabled ? "on" : "off"}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
