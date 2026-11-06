import { useEffect, useMemo, useState } from "react";
import {
  api,
  getTrialUser,
  setTrialUser,
  streamSynthesis,
  type Health,
  type MemoryRecord,
  type Paper,
  type Project,
  type SearchResponse,
  type Stats
} from "./api";

type TabId = "search" | "library" | "memory" | "synth" | "stats" | "about";

const TABS: { id: TabId; label: string; hint: string }[] = [
  { id: "search", label: "混合检索", hint: "向量 + 全文 + 过滤" },
  { id: "library", label: "文献库", hint: "导入与管理" },
  { id: "memory", label: "长期记忆", hint: "PowerContext" },
  { id: "synth", label: "综述生成", hint: "带引用对比" },
  { id: "stats", label: "使用统计", hint: "真实使用证据" },
  { id: "about", label: "关于项目", hint: "技术与验收" }
];

function shortId(value?: string) {
  if (!value) return "-";
  return value.length > 12 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
}

function normalizeTrialCode(value: string) {
  const match = value.trim().toUpperCase().match(/^U?(\d{1,2})$/);
  return match ? `U${match[1].padStart(2, "0")}` : value.trim();
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [tab, setTab] = useState<TabId>("search");
  const [papers, setPapers] = useState<Paper[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [booting, setBooting] = useState(true);
  const [trialUser, setTrialUserState] = useState(getTrialUser());

  const project = useMemo(
    () => projects.find((item) => item.id === projectId),
    [projects, projectId]
  );

  const visibleProjects = useMemo(
    () => (trialUser ? projects : projects.filter((item) => !item.id.startsWith("trial-"))),
    [projects, trialUser]
  );

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("u");
    if (fromUrl) {
      setTrialUser(normalizeTrialCode(fromUrl));
      setTrialUserState(getTrialUser());
    }
    const trialCode = normalizeTrialCode(fromUrl || getTrialUser()).toUpperCase();
    (async () => {
      try {
        const [healthData, projectData] = await Promise.all([api.health(), api.projects()]);
        setHealth(healthData);
        setProjects(projectData.projects);
        if (projectData.projects.length > 0) {
          const trialProject = trialCode
            ? projectData.projects.find((item) =>
                `${item.name} ${item.id}`.toUpperCase().includes(trialCode)
              )
            : undefined;
          const defaultProject =
            projectData.projects.find((item) => item.id === "demo") ||
            projectData.projects.find((item) => !item.id.startsWith("trial-"));
          setProjectId(trialProject?.id || defaultProject?.id || projectData.projects[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!projectId) return;
    (async () => {
      try {
        const [paperData, memoryData, statsData] = await Promise.all([
          api.papers(projectId),
          api.memory(projectId),
          api.stats(projectId)
        ]);
        setPapers(paperData.papers);
        setMemories(memoryData.memories);
        setStats(statsData);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [projectId]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const refreshProject = async () => {
    if (!projectId) return;
    const [paperData, memoryData, statsData, healthData] = await Promise.all([
      api.papers(projectId),
      api.memory(projectId),
      api.stats(projectId),
      api.health()
    ]);
    setPapers(paperData.papers);
    setMemories(memoryData.memories);
    setStats(statsData);
    setHealth(healthData);
  };

  const toggleSelect = (paperId: string) => {
    setSelected((current) =>
      current.includes(paperId)
        ? current.filter((id) => id !== paperId)
        : [...current, paperId]
    );
  };

  const handleCreated = (created: Project) => {
    setProjects((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    setProjectId(created.id);
    setToast("项目已创建，PowerContext Scope 已初始化");
  };

  if (booting) {
    return (
      <div className="loading-screen">
        <div className="spinner" />
        <p>正在连接 seekdb 与 PowerContext…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">PL</div>
          <div>
            <div className="brand-name">PaperLens</div>
            <div className="brand-sub">文澜 · 科研工作台</div>
          </div>
        </div>

        <nav className="nav">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${tab === item.id ? "active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className={`dot ${health?.powercontext ? "ok" : "bad"}`} />
          PowerContext {health?.powercontext ? "已连接" : "未连接"}
          <div className="divider" />
          <div className={`dot ${health?.llm_configured ? "ok" : "warn"}`} />
          {health?.llm_configured ? "LLM 已配置" : "离线抽取模式"}
          <div className="divider" />
          <a href="/api/health" target="_blank" rel="noreferrer">
            查看健康状态
          </a>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <div className="project-switch">
              <span className="label">当前项目</span>
              <select
                value={projectId}
                onChange={(event) => {
                  setProjectId(event.target.value);
                  setSelected([]);
                }}
              >
                {visibleProjects.length === 0 && <option value="">尚未创建</option>}
                {visibleProjects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
            <label className="trial-user" title="试用编号（如 U01），用于按人区分使用记录与长期记忆">
              <span className="label">试用者</span>
              <input
                value={trialUser}
                maxLength={16}
                placeholder="未设置"
                onChange={(event) => {
                  const value = event.target.value;
                  setTrialUserState(value);
                  setTrialUser(value);
                }}
              />
            </label>
          </div>
          <div className="badges">
            <span className="badge blue">seekdb · {health?.seekdb.embedding ?? "-"}</span>
            <span className="badge purple">PowerContext · {project?.scope_id ? "scope 已绑定" : "未绑定"}</span>
            <span className="badge gray">{papers.length} 篇文献</span>
          </div>
        </header>

        {error && (
          <div className="error-banner">
            {error}
            <button className="link-btn" onClick={() => setError("")}>
              关闭
            </button>
          </div>
        )}

        {!projectId ? (
          <Onboarding onCreated={handleCreated} />
        ) : (
          <div className="content">
            {tab === "search" && (
              <SearchTab
                projectId={projectId}
                selected={selected}
                toggleSelect={toggleSelect}
                onToast={setToast}
              />
            )}
            {tab === "library" && (
              <LibraryTab
                projectId={projectId}
                papers={papers}
                onRefresh={refreshProject}
                onToast={setToast}
              />
            )}
            {tab === "memory" && (
              <MemoryTab
                projectId={projectId}
                scopeId={project?.scope_id}
                memories={memories}
                onRefresh={refreshProject}
                onToast={setToast}
              />
            )}
            {tab === "synth" && (
              <SynthTab
                projectId={projectId}
                papers={papers}
                selected={selected}
                toggleSelect={toggleSelect}
                llmReady={Boolean(health?.llm_configured)}
                onToast={setToast}
              />
            )}
            {tab === "stats" && (
              <StatsTab projectId={projectId} stats={stats} onRefresh={refreshProject} />
            )}
            {tab === "about" && <AboutTab scopeId={project?.scope_id} />}
          </div>
        )}
      </main>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function Onboarding({ onCreated }: { onCreated: (project: Project) => void }) {
  const [name, setName] = useState("我的科研项目");
  const [question, setQuestion] = useState("");
  const [focus, setFocus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!name.trim()) {
      setError("请填写项目名称");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const created = await api.createProject({
        name,
        research_question: question,
        preferences: {
          language: "中文",
          style: "简洁，先给结论，再给证据",
          focus,
          venues_avoid: ""
        }
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="onboarding">
      <div className="hero">
        <div className="eyebrow">Qoder × OceanBase 参赛作品</div>
        <h1>让每一次文献检索都记得你的研究方向</h1>
        <p>
          PaperLens 用 seekdb 做向量 + 全文 + 标量的混合检索，用 PowerContext 记住你的偏好、已读进度与反馈。
          先创建一个研究项目，系统会自动建立长期记忆 Scope。
        </p>
      </div>
      <div className="card">
        <h2>创建研究项目</h2>
        <label>
          项目名称
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          研究问题（可选）
          <input
            value={question}
            placeholder="例如：LLM Agent 的记忆与评测方法如何比较？"
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
        <label>
          关注点（会写入 PowerContext，作为长期偏好）
          <input
            value={focus}
            placeholder="例如：方法对比、实验可复现性、局限性分析"
            onChange={(event) => setFocus(event.target.value)}
          />
        </label>
        {error && <div className="inline-error">{error}</div>}
        <button className="button primary" onClick={submit} disabled={loading}>
          {loading ? "创建中…" : "创建项目并初始化记忆"}
        </button>
        <p className="muted">
          也可以先运行 <code>make seed</code>，直接载入 20 篇 arXiv 文献的演示项目。
        </p>
      </div>
    </div>
  );
}

function SearchTab({
  projectId,
  selected,
  toggleSelect,
  onToast
}: {
  projectId: string;
  selected: string[];
  toggleSelect: (paperId: string) => void;
  onToast: (message: string) => void;
}) {
  const [query, setQuery] = useState("How do LLM agents remember and plan?");
  const [keyword, setKeyword] = useState("");
  const [yearMin, setYearMin] = useState("");
  const [venue, setVenue] = useState("");
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [feedbackSent, setFeedbackSent] = useState<Record<string, boolean>>({});

  const submit = async () => {
    if (!query.trim()) {
      onToast("请输入检索问题");
      return;
    }
    setLoading(true);
    try {
      const data = await api.search({
        project_id: projectId,
        query,
        keyword: keyword || null,
        year_min: yearMin ? Number(yearMin) : null,
        venue: venue || null,
        n_results: 8,
        memory_enabled: memoryEnabled
      });
      setResponse(data);
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const sendFeedback = async (paperId: string, relevant: boolean) => {
    try {
      await api.feedback({
        project_id: projectId,
        paper_id: paperId,
        relevant,
        comment: "",
        rating: relevant ? 5 : 2
      });
      setFeedbackSent((current) => ({ ...current, [paperId]: true }));
      onToast("反馈已记录，并写入 PowerContext 长期记忆");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>混合检索</h2>
            <p className="muted">
              seekdb 同时执行向量语义检索与全文关键词检索，再用 RRF 融合；元数据条件在候选集内过滤。
            </p>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={memoryEnabled}
              onChange={(event) => setMemoryEnabled(event.target.checked)}
            />
            <span>启用长期记忆</span>
          </label>
        </div>
        <label>
          研究问题
          <textarea
            rows={3}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：哪些方法解决了 LLM Agent 的长期记忆一致性问题？"
          />
        </label>
        <div className="form-grid">
          <label>
            精确关键词（可选，全文检索）
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="memory / causal" />
          </label>
          <label>
            年份下限（可选）
            <input value={yearMin} onChange={(event) => setYearMin(event.target.value)} placeholder="2024" type="number" />
          </label>
          <label>
            期刊/来源（可选）
            <input value={venue} onChange={(event) => setVenue(event.target.value)} placeholder="arXiv" />
          </label>
        </div>
        <button className="button primary" onClick={submit} disabled={loading}>
          {loading ? "检索中…" : "开始混合检索"}
        </button>
      </div>

      {response && (
        <>
          <div className="memory-strip">
            <div className="memory-strip-head">
              <strong>本次召回的记忆</strong>
              <span>{response.used_memories.length} 条 · {response.latency_ms} ms</span>
            </div>
            {response.used_memories.length === 0 ? (
              <p className="muted">
                未召回记忆。可到「长期记忆」页添加偏好，或开启记忆开关后重试。
              </p>
            ) : (
              <div className="chips">
                {response.used_memories.map((memory, index) => (
                  <span className="chip purple" key={`${memory.text}-${index}`}>
                    {memory.kind} · {memory.text.slice(0, 60)}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="results">
            {response.results.length === 0 && (
              <div className="empty">没有命中结果，试试放宽年份或去掉精确关键词。</div>
            )}
            {response.results.map((result) => (
              <article className="result-card" key={result.paper_id}>
                <div className="result-head">
                  <div>
                    <h3>{result.title}</h3>
                    <div className="meta">
                      {result.year || "—"} · {result.venue || "未知来源"}
                      {result.arxiv_id ? ` · arXiv:${result.arxiv_id}` : ""}
                    </div>
                    <div className="authors">{result.authors || "作者未知"}</div>
                  </div>
                  <div className="result-actions">
                    <button className="button ghost small" onClick={() => toggleSelect(result.paper_id)}>
                      {selected.includes(result.paper_id) ? "移出综述" : "加入综述"}
                    </button>
                  </div>
                </div>
                <p className="snippet">{result.snippet}</p>
                <div className="chunks">
                  {result.chunks.slice(0, 2).map((chunk) => (
                    <div className="chunk" key={chunk.id}>
                      <span className="chip">
                        {chunk.section || "body"}
                        {chunk.page ? ` · p.${chunk.page}` : ""}
                      </span>
                      <p>{chunk.text.slice(0, 320)}</p>
                    </div>
                  ))}
                </div>
                <div className="feedback-row">
                  <span className="muted">这条结果对你有帮助吗？</span>
                  {feedbackSent[result.paper_id] ? (
                    <span className="chip green">已写入记忆</span>
                  ) : (
                    <>
                      <button className="button ghost small" onClick={() => sendFeedback(result.paper_id, true)}>
                        相关
                      </button>
                      <button className="button ghost small" onClick={() => sendFeedback(result.paper_id, false)}>
                        不相关
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function LibraryTab({
  projectId,
  papers,
  onRefresh,
  onToast
}: {
  projectId: string;
  papers: Paper[];
  onRefresh: () => Promise<void>;
  onToast: (message: string) => void;
}) {
  const [arxivUrl, setArxivUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [busy, setBusy] = useState(false);

  const importArxiv = async () => {
    if (!arxivUrl.trim()) {
      onToast("请输入 arXiv 链接或编号");
      return;
    }
    setBusy(true);
    try {
      const paper = await api.importArxiv(projectId, arxivUrl.trim());
      onToast(`已导入：${paper.title}`);
      setArxivUrl("");
      await onRefresh();
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const uploadPdf = async () => {
    if (!file) {
      onToast("请选择 PDF 文件");
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("project_id", projectId);
      form.append("file", file);
      if (title) form.append("title", title);
      if (year) form.append("year", year);
      const paper = await api.uploadPdf(form);
      onToast(`已解析：${paper.title}`);
      setFile(null);
      setTitle("");
      setYear("");
      await onRefresh();
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const toggleRead = async (paper: Paper) => {
    try {
      await api.setRead(paper.id, paper.read_status ? 0 : 1);
      await onRefresh();
      onToast(paper.read_status ? "已取消已读" : "已标记已读，并写入阅读进度记忆");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="stack">
      <div className="grid two">
        <div className="card">
          <h2>导入 arXiv 文献</h2>
          <p className="muted">粘贴 abs/pdf 链接或编号，自动抓取元数据、下载 PDF、分块并写入 seekdb。</p>
          <input
            value={arxivUrl}
            onChange={(event) => setArxivUrl(event.target.value)}
            placeholder="https://arxiv.org/abs/2401.12345"
          />
          <button className="button primary" onClick={importArxiv} disabled={busy}>
            {busy ? "导入中…" : "导入并建立索引"}
          </button>
        </div>
        <div className="card">
          <h2>上传本地 PDF</h2>
          <p className="muted">适合课程论文、组会材料与未公开稿件；文本型 PDF 可直接解析。</p>
          <input type="file" accept="application/pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="form-grid two-cols">
            <label>
              标题（可选）
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label>
              年份（可选）
              <input value={year} onChange={(event) => setYear(event.target.value)} type="number" />
            </label>
          </div>
          <button className="button primary" onClick={uploadPdf} disabled={busy || !file}>
            {busy ? "解析中…" : "上传并建立索引"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>文献库</h2>
          <span className="badge gray">{papers.length} 篇</span>
        </div>
        <div className="paper-list">
          {papers.length === 0 && <div className="empty">还没有文献，先导入一篇 arXiv 论文试试。</div>}
          {papers.map((paper) => (
            <div className="paper-row" key={paper.id}>
              <div>
                <div className="paper-title">{paper.title}</div>
                <div className="meta">
                  {paper.year || "—"} · {paper.venue || "未知来源"}
                  {paper.arxiv_id ? ` · arXiv:${paper.arxiv_id}` : ""}
                </div>
                <div className="authors">{paper.authors}</div>
              </div>
              <button
                className={`button small ${paper.read_status ? "ghost" : "primary"}`}
                onClick={() => toggleRead(paper)}
              >
                {paper.read_status ? "已读" : "标记已读"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function MemoryTab({
  projectId,
  scopeId,
  memories,
  onRefresh,
  onToast
}: {
  projectId: string;
  scopeId?: string;
  memories: MemoryRecord[];
  onRefresh: () => Promise<void>;
  onToast: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("preference");
  const [busy, setBusy] = useState(false);

  const remember = async () => {
    if (!text.trim()) {
      onToast("请输入记忆内容");
      return;
    }
    setBusy(true);
    try {
      await api.remember({ project_id: projectId, text: text.trim(), kind, reason: "用户在记忆面板手动添加" });
      setText("");
      await onRefresh();
      onToast("已写入 PowerContext");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const forget = async (memory: MemoryRecord) => {
    if (!memory.artifact || memory.state_version === undefined) {
      onToast("该记忆缺少 artifact 引用，无法遗忘");
      return;
    }
    try {
      await api.forget({
        project_id: projectId,
        artifact: memory.artifact,
        state_version: memory.state_version
      });
      await onRefresh();
      onToast("已遗忘该记忆（历史仍保留可恢复）");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>PowerContext 长期记忆</h2>
            <p className="muted">
              记忆保存在对话之外，跨会话复用。Scope：{scopeId ? shortId(scopeId) : "未绑定"}。
              每次检索与综述都会留下读写 trace，可在 evidence/powercontext 中核对。
            </p>
          </div>
          <span className="badge purple">{memories.length} 条 active</span>
        </div>
        <div className="form-grid two-cols">
          <label>
            新增记忆
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="例如：优先阅读 2024 年后的实验类论文"
            />
          </label>
          <label>
            类型
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="preference">偏好 preference</option>
              <option value="interest">兴趣 interest</option>
              <option value="negative-interest">否定 negative-interest</option>
              <option value="progress">进度 progress</option>
              <option value="focus">关注点 focus</option>
              <option value="decision">决策 decision</option>
            </select>
          </label>
        </div>
        <button className="button primary" onClick={remember} disabled={busy}>
          {busy ? "写入中…" : "写入长期记忆"}
        </button>
      </div>

      <div className="memory-list">
        {memories.length === 0 && <div className="empty">还没有记忆。创建项目时会写入初始偏好。</div>}
        {memories.map((memory, index) => (
          <div className="memory-card" key={`${memory.text}-${index}`}>
            <div className="memory-card-head">
              <span className="chip purple">{memory.kind}</span>
              <span className="meta">{shortId((memory.artifact as any)?.artifact_id)}</span>
            </div>
            <p>{memory.text}</p>
            <button className="button ghost small" onClick={() => forget(memory)}>
              遗忘
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function SynthTab({
  projectId,
  papers,
  selected,
  toggleSelect,
  llmReady,
  onToast
}: {
  projectId: string;
  papers: Paper[];
  selected: string[];
  toggleSelect: (paperId: string) => void;
  llmReady: boolean;
  onToast: (message: string) => void;
}) {
  const [question, setQuestion] = useState(
    "比较这些论文在方法、实验设计与局限性上的差异，并给出后续阅读建议。"
  );
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [usedMemories, setUsedMemories] = useState<MemoryRecord[]>([]);
  const [llmConfigured, setLlmConfigured] = useState(llmReady);
  const [latency, setLatency] = useState<number | null>(null);
  const [invalidCitations, setInvalidCitations] = useState<number[]>([]);

  const run = async () => {
    if (selected.length === 0) {
      onToast("请先在检索结果或左侧列表选择文献");
      return;
    }
    if (!question.trim()) {
      onToast("请输入综述问题");
      return;
    }
    setRunning(true);
    setOutput("");
    setUsedMemories([]);
    setLatency(null);
    setInvalidCitations([]);
    try {
      await streamSynthesis(
        {
          project_id: projectId,
          paper_ids: selected,
          question,
          memory_enabled: memoryEnabled
        },
        (event) => {
          if (event.type === "meta") {
            setUsedMemories(event.used_memories || []);
            setLlmConfigured(Boolean(event.llm_configured));
          } else if (event.type === "delta" && event.content) {
            setOutput((current) => current + event.content);
          } else if (event.type === "done") {
            setLatency(event.latency_ms ?? null);
            setInvalidCitations(event.invalid_citations ?? []);
          } else if (event.type === "error") {
            onToast(event.message || "生成失败");
          }
        }
      );
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const exportMarkdown = () => {
    if (!output) return;
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const selectedPapers = papers.filter((p) => selected.includes(p.id));
    const lines = [
      `# ${question}`,
      "",
      `> 生成时间：${now.toISOString()}`,
      `> 文献数量：${selectedPapers.length} 篇`,
      latency !== null ? `> 延迟：${latency} ms` : null,
      "",
      "## 引用的文献",
      ...selectedPapers.map((p, i) => `- [P${i + 1}] ${p.title}${p.year ? ` (${p.year})` : ""}`),
      "",
      "## 综述正文",
      "",
      output,
    ];
    const content = lines.filter((l) => l !== null).join("\n");
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `synthesis-${timestamp}.md`;
    a.click();
    URL.revokeObjectURL(url);
    onToast("已导出 Markdown 文件");
  };

  return (
    <section className="stack">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>综述与对比生成</h2>
            <p className="muted">
              选中的文献会连同检索片段一起送入模型；每条结论要求标注 [P#] 引用。
              记忆开关用于对比“有/无长期偏好”的输出差异。
            </p>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={memoryEnabled}
              onChange={(event) => setMemoryEnabled(event.target.checked)}
            />
            <span>启用长期记忆</span>
          </label>
        </div>
        <label>
          综述问题
          <textarea rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        <button className="button primary" onClick={run} disabled={running}>
          {running ? "生成中…" : "生成带引用的综述"}
        </button>
      </div>

      <div className="synth-grid">
        <div className="card">
          <div className="card-head">
            <h3>选择文献</h3>
            <span className="badge gray">{selected.length} 篇已选</span>
          </div>
          <div className="pick-list">
            {papers.length === 0 && <div className="empty">文献库为空，请先导入。</div>}
            {papers.map((paper) => (
              <label className={`pick-item ${selected.includes(paper.id) ? "on" : ""}`} key={paper.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(paper.id)}
                  onChange={() => toggleSelect(paper.id)}
                />
                <span>
                  <strong>{paper.title}</strong>
                  <small>
                    {paper.year || "—"} · {paper.venue || "未知来源"}
                  </small>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div className="card output-card">
          <div className="card-head">
            <h3>生成结果</h3>
            <div className="badges">
              {latency !== null && <span className="badge gray">{latency} ms</span>}
              <span className={`badge ${llmConfigured ? "blue" : "warn"}`}>
                {llmConfigured ? "LLM 生成" : "离线抽取"}
              </span>
              <button
                className="button ghost small"
                onClick={exportMarkdown}
                disabled={!output}
              >
                导出 Markdown
              </button>
            </div>
          </div>
          {usedMemories.length > 0 && (
            <div className="chips">
              {usedMemories.map((memory, index) => (
                <span className="chip purple" key={`${memory.text}-${index}`}>
                  记忆：{memory.text.slice(0, 50)}
                </span>
              ))}
            </div>
          )}
          {invalidCitations.length > 0 && (
            <div className="citation-warning">
              <strong>引用校验失败：</strong>
              以下引用编号不在所选文献范围内（1–{selected.length}）：
              {invalidCitations.map((n) => (
                <span className="chip red" key={n}>[P{n}]</span>
              ))}
            </div>
          )}
          {output ? (
            <div className="markdown">{output}</div>
          ) : (
            <div className="empty">生成结果会显示在这里，并以 SSE 流式输出。</div>
          )}
        </div>
      </div>
    </section>
  );
}

function StatsTab({
  projectId,
  stats,
  onRefresh
}: {
  projectId: string;
  stats: Stats | null;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  const searchCount = stats?.events.find((item) => item.action === "search")?.count ?? 0;
  const synthCount = stats?.events.find((item) => item.action === "synthesize")?.count ?? 0;

  const exportUsage = async () => {
    setBusy(true);
    try {
      const response = await fetch(`/api/export/usage?project_id=${encodeURIComponent(projectId)}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `paperlens-usage-${projectId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="stack">
      <div className="metric-grid">
        <div className="metric">
          <span>文献</span>
          <strong>{stats?.papers ?? 0}</strong>
        </div>
        <div className="metric">
          <span>试用者</span>
          <strong>{stats?.users ?? 0}</strong>
        </div>
        <div className="metric">
          <span>检索次数</span>
          <strong>{searchCount}</strong>
        </div>
        <div className="metric">
          <span>综述次数</span>
          <strong>{synthCount}</strong>
        </div>
        <div className="metric">
          <span>反馈数</span>
          <strong>{stats?.feedback.count ?? 0}</strong>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>真实使用记录</h2>
            <p className="muted">
              这里的数据来自应用自身的事件表，可直接导出为 CSV/JSON，作为「使用效果」证据。
            </p>
          </div>
          <div className="result-actions">
            <button className="button ghost small" onClick={() => onRefresh()}>
              刷新
            </button>
            <button className="button primary small" onClick={exportUsage} disabled={busy}>
              {busy ? "导出中…" : "导出使用数据"}
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>动作</th>
                <th>次数</th>
                <th>平均耗时</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.events || []).map((item) => (
                <tr key={item.action}>
                  <td>{item.action}</td>
                  <td>{item.count}</td>
                  <td>{item.avg_latency_ms ? `${Math.round(item.avg_latency_ms)} ms` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>最近事件</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>动作</th>
                <th>输入</th>
                <th>耗时</th>
                <th>结果数</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.recent_events || []).map((event, index) => (
                <tr key={`${event.created_at}-${index}`}>
                  <td>{event.created_at}</td>
                  <td>{event.action}</td>
                  <td className="ellipsis">{event.query || "—"}</td>
                  <td>{event.latency_ms} ms</td>
                  <td>{event.result_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function AboutTab({ scopeId }: { scopeId?: string }) {
  return (
    <section className="stack">
      <div className="card hero-card">
        <div className="eyebrow">Build with Qoder</div>
        <h1>PaperLens 文澜</h1>
        <p>
          面向科研文献的混合检索与记忆增强综述工作台。项目使用 Qoder 开发，通过 Qoder Sites 发布展示站，
          核心功能由 seekdb 与 PowerContext 共同驱动。
        </p>
      </div>
      <div className="grid two">
        <div className="card">
          <h3>seekdb 的作用</h3>
          <ul>
            <li>存储论文分块与元数据（年份、来源、作者、页码）</li>
            <li>同一次查询内完成向量语义检索、全文关键词检索与标量过滤</li>
            <li>RRF 融合后返回带分数的证据片段，供综述引用</li>
            <li>所有检索参数与结果写入 trace，可逐条核对</li>
          </ul>
        </div>
        <div className="card">
          <h3>PowerContext 的作用</h3>
          <ul>
            <li>保存语言/风格偏好、研究关注点、已读进度与反馈</li>
            <li>检索与生成前召回 PreparedContext，影响输出策略</li>
            <li>记忆拥有 artifact 引用与版本，可审计、可遗忘、可恢复</li>
            <li>当前 Scope：{scopeId ? shortId(scopeId) : "未绑定"}</li>
          </ul>
        </div>
      </div>
      <div className="card">
        <h3>一键验收</h3>
        <pre className="code-block">{`cp .env.example .env   # 配置 OPENAI_*
docker compose up --build -d
make seed
make verify
make evidence`}</pre>
        <p className="muted">
          验收脚本会检查：seed 语料、混合检索、标量过滤、记忆写入与召回、流式综述、审计 trace。
          证据输出在 evidence/verification 与 evidence/usage。
        </p>
      </div>
    </section>
  );
}
