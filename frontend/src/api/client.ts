// Thin typed client for the Career Agent backend.

export interface ContactInfo {
  name: string;
  headline?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  linkedin?: string | null;
  github?: string | null;
  website?: string | null;
}

export interface ExperienceItem {
  title: string;
  company: string;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  bullets: string[];
}

export interface ProjectItem {
  name: string;
  description?: string | null;
  tech: string[];
  link?: string | null;
  bullets: string[];
}

export interface EducationItem {
  degree: string;
  institution: string;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  details?: string | null;
}

export interface SkillGroup {
  category: string;
  skills: string[];
}

export interface CertificationItem {
  name: string;
  date?: string | null;
  url?: string | null;
}

export interface ExtraSection {
  title: string;
  items: string[];
}

export interface ResumeData {
  contact: ContactInfo;
  summary?: string | null;
  skills: string[];
  skill_groups?: SkillGroup[];
  experience: ExperienceItem[];
  projects: ProjectItem[];
  education: EducationItem[];
  certifications: CertificationItem[];
  extra_sections?: ExtraSection[];
  section_order?: string[];
  layout?: { page_size?: string | null; pages?: number | null };
}

export interface AtsComponent {
  name: string;
  score: number;
  max: number;
  detail: string;
}

export interface AtsReport {
  score: number;
  components: AtsComponent[];
  matched_keywords: string[];
  missing_keywords: string[];
  suggestions: string[];
}

export interface UploadResponse {
  resume_id: number;
  parsed: ResumeData;
  raw_text_chars: number;
  warning?: string | null;
  reused?: boolean;
}

export interface ResumeSummary {
  id: number;
  created_at: string;
  filename?: string | null;
  name: string;
  complete: boolean;
}

export interface TailoringSummary {
  id: number;
  resume_id: number;
  created_at: string;
  role: string;
  role_label: string;
  ats_score?: number | null;
  job_snippet?: string | null;
}

export interface BulletReview {
  section: "experience" | "projects" | "project_description" | "summary" | "headline";
  entry: number;
  index: number;
  label: string;
  original: string;
  suggested: string;
  flags: string[];
  applied: boolean;
}

export interface TailorResponse {
  tailoring_id: number;
  resume_id: number;
  role: string;
  tailored: ResumeData;
  ats: AtsReport;
  iterations?: number | null;
  pdf_available: boolean;
  docx_available: boolean;
  warning?: string | null;
  baseline_score?: number | null;
  job_description?: string | null;
  reviews?: BulletReview[];
}

export interface EmailLogOut {
  id: number;
  to_email: string;
  subject?: string | null;
  status: string;
  error?: string | null;
}

export interface RoleOption {
  key: string;
  label: string;
}

export interface GeneratedMessage {
  channel: string;
  subject?: string | null;
  body: string;
}

export interface CandidateProfile {
  candidate_name: string;
  highlights: string[];
}

export interface JobOut {
  id: number;
  source: string;
  title: string;
  company: string;
  location?: string | null;
  job_type?: string | null;
  experience?: string | null;
  role_category?: string | null;
  url?: string | null;
  recruiter_name?: string | null;
  recruiter_email?: string | null;
  description?: string | null;
  created_at?: string | null;
  match_score?: number | null;
  match_matched?: string[];
  match_missing?: string[];
  application_id?: number | null;
  application_status?: ApplicationStatus | null;
  is_new?: boolean;
}

export const APPLICATION_STATUSES = [
  "saved",
  "applied",
  "contacted",
  "replied",
  "interview",
  "offer",
  "rejected",
] as const;
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export interface ApplicationOut {
  id: number;
  created_at: string;
  updated_at?: string | null;
  job_id?: number | null;
  company: string;
  role: string;
  url?: string | null;
  location?: string | null;
  status: ApplicationStatus;
  tailoring_id?: number | null;
  tailoring_score?: number | null;
  recruiter_email?: string | null;
  notes?: string | null;
  applied_at?: string | null;
  contacted_at?: string | null;
  emails_sent: number;
  last_emailed_at?: string | null;
}

export interface ExtractorResult {
  name: string;
  score: number;
  word_coverage: number;
  bullets_intact: number;
  issues: string[];
  preview: string;
}

export interface AtsCheckReport {
  verdict: "excellent" | "good" | "risky";
  score: number;
  extractors: ExtractorResult[];
  notes: string[];
}

export interface ScanReport {
  seen_words: number;
  seen_text: string;
  keywords_in_view: string[];
  keywords_buried: string[];
  metrics_in_view: number;
  metrics_total: number;
  tips: string[];
}

export interface EvidenceLine {
  id: number;
  where: string;
  text: string;
}

export interface Requirement {
  text: string;
  kind: "must" | "nice";
  status: "met" | "partial" | "gap";
  evidence: EvidenceLine[];
  note: string;
}

export interface EvidenceReport {
  requirements: Requirement[];
  red_flags: { text: string; why: string }[];
  must_met: number;
  must_total: number;
  nice_met: number;
  nice_total: number;
  years_required?: number | null;
  years_candidate: number;
}

export interface DrillQuestion {
  claim_id: number;
  where: string;
  claim: string;
  question: string;
  look_for: string[];
}

export interface DrillGrade {
  verdict: "defended" | "shaky" | "undefended";
  score: number;
  feedback: string;
  follow_up?: string | null;
  safer_wording?: string | null;
}

/** A check target: an optimized version, or the original upload (+ role). */
export type CheckTarget = { tailoringId: number } | { resumeId: number; role: string };

const checkQuery = (t: CheckTarget) =>
  "tailoringId" in t
    ? `tailoring_id=${t.tailoringId}`
    : `resume_id=${t.resumeId}&role=${encodeURIComponent(t.role)}`;

export interface TaskOut {
  id: number;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  created_at: string;
  run_at?: string | null;
  finished_at?: string | null;
  progress?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  outward: boolean;
  summary: string;
}

export interface Health {
  status: "ok" | "degraded";
  problems: string[];
  database: boolean;
  worker: { alive: boolean; last_heartbeat?: string | null; running: number };
  queue: { queued: number; running: number; failed_24h: number };
  automation_paused: boolean;
  last_backup?: string | null;
  copilot_credits_today: number;
  copilot_daily_budget: number;
}

export interface SystemEvent {
  id: number;
  created_at: string;
  kind: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface Usage {
  days: number;
  providers: {
    provider: string;
    calls: number;
    ok: number;
    avg_latency_ms: number;
    input_tokens: number;
    output_tokens: number;
    credits: number;
    fallbacks: number;
  }[];
  by_purpose: Record<string, number>;
  copilot_credits_today: number;
  copilot_daily_budget: number;
  recent_errors: { created_at: string; purpose: string; error: string }[];
}

export interface BackupItem {
  name: string;
  size: number;
  created_at: string;
}

/** Poll a background task until it finishes (succeeded, failed or cancelled). */
export async function waitForTask(
  id: number,
  onUpdate?: (t: TaskOut) => void,
  intervalMs = 1500
): Promise<TaskOut> {
  for (;;) {
    const t = await api.task(id);
    onUpdate?.(t);
    if (t.status === "succeeded" || t.status === "failed" || t.status === "cancelled") return t;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export interface ContactHistory {
  email: string;
  count: number;
  last_sent_at?: string | null;
}

export interface ProviderStatus {
  name: string;
  configured: boolean;
  model: string;
}

export interface EmailProviderStatus {
  name: string;
  enabled: boolean;
}

export interface SettingsStatus {
  providers: ProviderStatus[];
  smtp_configured: boolean;
  tectonic_available: boolean;
  roles: string[];
  email_providers: EmailProviderStatus[];
  linkedin_enabled: boolean;
  linkedin_available: boolean;
  env_overrides?: string[];
  company_boards?: number;
  auto_refresh_hours?: number;
  digest_email?: string | null;
}

export interface ConnectionTest {
  name: string;
  ok: boolean;
  latency_ms?: number | null;
  detail: string;
}

export interface LinkedInStatus {
  enabled: boolean;
  playwright_available: boolean;
  logged_in: boolean;
}

export interface LinkedInLogOut {
  id: number;
  profile_url: string;
  recipient_name?: string | null;
  status: string;
  error?: string | null;
}

export interface LinkedInSendItem {
  profile_url: string;
  message: string;
  recipient_name?: string;
  message_id?: number;
}

export interface EmailCandidateOut {
  email: string;
  source: string;
  confidence: number;
  verified: string; // unverified | mx_only | verified
  name?: string | null;
}

export interface EmailFindResponse {
  candidates: EmailCandidateOut[];
  best?: EmailCandidateOut | null;
  domain?: string | null;
}

export interface SendItem {
  to_email: string;
  subject: string;
  body: string;
  recruiter_name?: string;
  company?: string;
  role?: string;
  tailoring_id?: number;
  job_id?: number;
}

export interface BatchSendResponse {
  results: { to_email: string; status: string; error?: string | null }[];
  sent: number;
  failed: number;
  queued: number;
}

/** Human-readable message for any thrown value (no "Error: " prefix). */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

const TOKEN_KEY = "ca.apiToken";

export function getApiToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

/** Saved for API calls and as a cookie, so plain links (downloads, images) work too. */
export function setApiToken(token: string) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable: the cookie still works for this session */
  }
  document.cookie = `ca_token=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const token = getApiToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    res = await fetch(url, { ...init, headers });
  } catch {
    throw new Error("Can't reach the backend. Is it running on port 8000?");
  }
  if (res.status === 401) {
    window.dispatchEvent(new Event("ca:unauthorized"));
    throw new Error("This Career Agent needs an access token.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : Array.isArray(body.detail)
          ? body.detail.map((d: { msg?: string }) => d.msg).join("; ")
          : JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  status: () => request<SettingsStatus>("/api/settings/status"),
  testLlm: () => request<ConnectionTest[]>("/api/settings/test-llm", { method: "POST" }),
  testSmtp: () => request<ConnectionTest>("/api/settings/test-smtp", { method: "POST" }),

  roles: () => request<RoleOption[]>("/api/resume/roles"),
  resumes: () => request<ResumeSummary[]>("/api/resume"),
  resume: (id: number) => request<UploadResponse>(`/api/resume/${id}`),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<UploadResponse>("/api/resume/upload", { method: "POST", body: fd });
  },

  score: (body: { resume: ResumeData; role: string; job_description?: string }) =>
    request<AtsReport>("/api/resume/score", json(body)),

  tailor: (body: {
    resume_id: number;
    role: string;
    job_description?: string;
    target_score?: number;
    max_iterations?: number;
    job_id?: number;
  }) => request<TaskOut>("/api/resume/tailor", json(body)),

  task: (id: number) => request<TaskOut>(`/api/system/tasks/${id}`),
  tasks: (status?: string) => request<TaskOut[]>(`/api/system/tasks${status ? `?status=${status}` : ""}`),
  cancelTask: (id: number) => request<TaskOut>(`/api/system/tasks/${id}/cancel`, { method: "POST" }),
  retryTask: (id: number) => request<TaskOut>(`/api/system/tasks/${id}/retry`, { method: "POST" }),
  health: () => request<Health>("/api/system/health"),
  events: (limit = 100) => request<SystemEvent[]>(`/api/system/events?limit=${limit}`),
  usage: (days = 7) => request<Usage>(`/api/system/usage?days=${days}`),
  backups: () => request<BackupItem[]>("/api/system/backups"),
  backupNow: () => request<TaskOut>("/api/system/backups", { method: "POST" }),
  backupUrl: (name: string) => `/api/system/backups/${encodeURIComponent(name)}`,
  setAutomation: (paused: boolean) => request<{ paused: boolean }>("/api/system/automation", json({ paused })),

  rerender: (tailoringId: number) =>
    request<TailorResponse>(`/api/resume/tailorings/${tailoringId}/render`, { method: "POST" }),

  atsCheck: (t: CheckTarget) => request<AtsCheckReport>(`/api/checks/ats?${checkQuery(t)}`),
  scan: (t: CheckTarget) => request<ScanReport>(`/api/checks/scan?${checkQuery(t)}`),
  scanImageUrl: (t: CheckTarget, bust = "") => `/api/checks/scan.png?${checkQuery(t)}${bust ? `&v=${bust}` : ""}`,
  evidence: (body: { resume_id: number; tailoring_id?: number; job_description?: string; job_id?: number }) =>
    request<EvidenceReport>("/api/checks/evidence", json(body)),

  drillQuestions: (body: { resume_id: number; tailoring_id?: number; count?: number }) =>
    request<DrillQuestion[]>("/api/drill/questions", json(body)),
  drillGrade: (body: { claim: string; question: string; look_for: string[]; answer: string }) =>
    request<DrillGrade>("/api/drill/grade", json(body)),

  applyReview: (tailoringId: number, applied: boolean[]) =>
    request<TailorResponse>(`/api/resume/tailorings/${tailoringId}/review`, json({ applied })),

  tailorings: (resumeId?: number) =>
    request<TailoringSummary[]>(
      `/api/resume/tailorings${resumeId ? `?resume_id=${resumeId}` : ""}`
    ),
  tailoring: (id: number) => request<TailorResponse>(`/api/resume/tailorings/${id}`),

  downloadUrl: (tailoringId: number, fmt: "pdf" | "docx" | "tex") =>
    `/api/resume/${tailoringId}/download?fmt=${fmt}`,

  profile: (tailoringId: number) =>
    request<CandidateProfile>(`/api/outreach/profile/${tailoringId}`),

  generateMessages: (body: {
    recruiter_name?: string | null;
    company: string;
    role: string;
    channel: string;
    candidate_name?: string | null;
    candidate_highlights: string[];
    tone: string;
    variants: number;
    job_id?: number;
    tailoring_id?: number;
  }) =>
    request<{ messages: GeneratedMessage[]; warning?: string | null }>(
      "/api/outreach/generate",
      json(body)
    ),

  sendBatch: (items: SendItem[], dryRun: boolean, allowRepeat = false) =>
    request<BatchSendResponse>(
      "/api/outreach/send",
      json({ items, dry_run: dryRun, allow_repeat: allowRepeat })
    ),

  contacted: (email: string) =>
    request<ContactHistory>(`/api/outreach/contacted?email=${encodeURIComponent(email)}`),

  applications: () => request<ApplicationOut[]>("/api/applications"),
  createApplication: (body: {
    job_id?: number;
    company?: string;
    role?: string;
    url?: string;
    status?: ApplicationStatus;
    notes?: string;
  }) => request<ApplicationOut>("/api/applications", json(body)),
  updateApplication: (
    id: number,
    body: { status?: ApplicationStatus; notes?: string; recruiter_email?: string }
  ) =>
    request<ApplicationOut>(`/api/applications/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteApplication: (id: number) =>
    request<{ ok: boolean }>(`/api/applications/${id}`, { method: "DELETE" }),

  sends: (limit = 50) => request<EmailLogOut[]>(`/api/outreach/sends?limit=${limit}`),

  jobsMeta: () =>
    request<{ sources: string[]; job_types: string[]; experience_levels: string[] }>(
      "/api/jobs/meta"
    ),

  job: (id: number) => request<JobOut>(`/api/jobs/${id}`),

  listJobs: (params: Record<string, string>) =>
    request<JobOut[]>(`/api/jobs?${new URLSearchParams(params).toString()}`),

  refreshJobs: (body: {
    source: string;
    query?: string;
    location?: string;
    limit?: number;
    enrich_emails?: boolean;
  }) => request<JobOut[]>("/api/jobs/refresh", json(body)),

  findEmail: (body: {
    company: string;
    name?: string;
    domain?: string;
    job_url?: string;
    job_id?: number;
  }) => request<EmailFindResponse>("/api/email/find", json(body)),

  linkedinStatus: () => request<LinkedInStatus>("/api/linkedin/status"),
  linkedinLogin: () =>
    request<{ status: string; detail: string }>("/api/linkedin/login", { method: "POST" }),
  linkedinSend: (items: LinkedInSendItem[], dryRun: boolean) =>
    request<BatchSendResponse>("/api/linkedin/send", json({ items, dry_run: dryRun })),
  linkedinSends: (limit = 50) => request<LinkedInLogOut[]>(`/api/linkedin/sends?limit=${limit}`),
};
