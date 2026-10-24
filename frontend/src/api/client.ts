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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error("Can't reach the backend. Is it running on port 8000?");
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
  }) => request<TailorResponse>("/api/resume/tailor", json(body)),

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

  sendBatch: (items: SendItem[], dryRun: boolean) =>
    request<BatchSendResponse>("/api/outreach/send", json({ items, dry_run: dryRun })),

  sends: (limit = 50) => request<EmailLogOut[]>(`/api/outreach/sends?limit=${limit}`),

  jobsMeta: () =>
    request<{ sources: string[]; job_types: string[]; experience_levels: string[] }>(
      "/api/jobs/meta"
    ),

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
