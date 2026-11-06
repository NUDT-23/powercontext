export interface SessionState {
  activeCollection: string | null;
  importedDocs: Record<string, number>;
  lastRefreshAt: Record<string, string | null>;
  lastBackend: string | null;
  lastQuery: string;
}

const KEY = "stepfun-kb-session-v1";

const EMPTY: SessionState = {
  activeCollection: null,
  importedDocs: {},
  lastRefreshAt: {},
  lastBackend: null,
  lastQuery: "",
};

export function loadSession(): SessionState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...EMPTY };
    const parsed = JSON.parse(raw) as Partial<SessionState>;
    return {
      ...EMPTY,
      ...parsed,
      importedDocs: parsed.importedDocs ?? {},
      lastRefreshAt: parsed.lastRefreshAt ?? {},
    };
  } catch {
    return { ...EMPTY };
  }
}

export function saveSession(state: SessionState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // session bookkeeping only; ignore quota errors
  }
}
