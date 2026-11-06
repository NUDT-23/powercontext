export type Project = {
  id: string;
  name: string;
  description: string;
  research_question: string;
  scope_id?: string;
  created_at?: string;
  warnings?: string[];
};

export type Paper = {
  id: string;
  project_id: string;
  title: string;
  authors: string;
  year: number | null;
  venue: string;
  arxiv_id: string;
  abstract: string;
  source: string;
  read_status: number;
  added_at: string;
};

export type Chunk = {
  id: string;
  text: string;
  distance?: number | null;
  section?: string;
  page?: number;
};

export type SearchResult = {
  paper_id: string;
  title: string;
  authors: string;
  year: number | null;
  venue: string;
  arxiv_id: string;
  snippet: string;
  chunks: Chunk[];
};

export type MemoryRecord = {
  text: string;
  kind: string;
  artifact?: Record<string, unknown>;
  state_version?: number;
  score?: number;
  matched_by?: string;
  created_at?: string;
};

export type SearchResponse = {
  query: string;
  memory_enabled: boolean;
  used_memories: MemoryRecord[];
  memory_context: string;
  latency_ms: number;
  results: SearchResult[];
};

export type Health = {
  status: string;
  seekdb: { papers: number; collection: string; embedding: string };
  powercontext: boolean;
  llm_configured: boolean;
};

export type Stats = {
  papers: number;
  users: number;
  events: { action: string; count: number; avg_latency_ms: number | null }[];
  feedback: { count: number; avg_rating: number | null };
  recent_events: {
    action: string;
    query: string;
    latency_ms: number;
    result_count: number;
    created_at: string;
  }[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail || JSON.stringify(body);
    } catch {
      try {
        message = await response.text();
      } catch {
        /* ignore */
      }
    }
    throw new Error(message || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function jsonOptions(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  };
}

const TRIAL_USER_KEY = "paperlens.trialUser";

export function getTrialUser(): string {
  return (window.localStorage.getItem(TRIAL_USER_KEY) || "").trim();
}

export function setTrialUser(value: string): void {
  const clean = value.trim().slice(0, 16);
  if (clean) window.localStorage.setItem(TRIAL_USER_KEY, clean);
  else window.localStorage.removeItem(TRIAL_USER_KEY);
}

function withTrialUser(body: Record<string, unknown>): Record<string, unknown> {
  const user = getTrialUser();
  return user ? { ...body, user_name: user } : body;
}

export const api = {
  health: () => request<Health>("/api/health"),
  projects: () => request<{ projects: Project[] }>("/api/projects"),
  createProject: (body: Record<string, unknown>) =>
    request<Project>("/api/projects", jsonOptions("POST", body)),
  papers: (projectId: string) =>
    request<{ papers: Paper[] }>(`/api/papers?project_id=${encodeURIComponent(projectId)}`),
  importArxiv: (projectId: string, url: string) =>
    request<Paper>("/api/papers/import_arxiv", jsonOptions("POST", { project_id: projectId, url })),
  uploadPdf: (form: FormData) => request<Paper>("/api/papers/upload", { method: "POST", body: form }),
  setRead: (paperId: string, readStatus: number) =>
    request<Paper>(`/api/papers/${paperId}/read`, jsonOptions("PATCH", { read_status: readStatus })),
  search: (body: Record<string, unknown>) =>
    request<SearchResponse>("/api/search", jsonOptions("POST", withTrialUser(body))),
  memory: (projectId: string) =>
    request<{ scope_id: string | null; memories: MemoryRecord[] }>(
      `/api/memory?project_id=${encodeURIComponent(projectId)}`
    ),
  remember: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/memory/remember", jsonOptions("POST", body)),
  forget: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/memory/forget", jsonOptions("POST", body)),
  feedback: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>("/api/feedback", jsonOptions("POST", withTrialUser(body))),
  stats: (projectId: string) =>
    request<Stats>(`/api/stats?project_id=${encodeURIComponent(projectId)}`)
};

export type SynthesisEvent = {
  type: "meta" | "delta" | "done" | "error";
  content?: string;
  message?: string;
  papers?: { id: string; title: string; year: number | null }[];
  used_memories?: MemoryRecord[];
  memory_context?: string;
  llm_configured?: boolean;
  latency_ms?: number;
  chars?: number;
  invalid_citations?: number[];
};

export async function streamSynthesis(
  payload: Record<string, unknown>,
  onEvent: (event: SynthesisEvent) => void
): Promise<void> {
  const response = await fetch("/api/synthesize", jsonOptions("POST", withTrialUser(payload)));
  if (!response.ok || !response.body) {
    throw new Error(`生成失败：HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const dataLine = part
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()) as SynthesisEvent);
      } catch {
        /* ignore malformed event */
      }
    }
  }
}
