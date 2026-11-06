# PaperLens 自动验收报告

- 结论：PASS
- 时间：2026-11-06T11:06:52.263393+00:00

| 检查项 | 结果 | 详情 |
| --- | --- | --- |
| health | PASS | {"status": "ok", "seekdb": {"papers": 260, "collection": "paper_chunks", "embedding": "local:all-MiniLM-L6-v2"}, "powercontext": true, "llm_configured": true} |
| seed_corpus | PASS | papers=20 |
| hybrid_search | PASS | results=7 latency_ms=167.94 |
| scalar_filter | PASS | results=6 years=[2026, 2026, 2026, 2026, 2025, 2025] |
| memory_write | PASS | memories=6 |
| memory_recall | PASS | used_memories=2 sample=Preference: when searching agent memory topics, prefer survey papers and always  |
| synthesis_stream | PASS | events=1169 chars=2003 llm=True |
| audit_traces | PASS | seekdb_records=46 pc_records=286 pc_ops=['capture_source', 'ensure_scope', 'forget_memory', 'list_memory', 'prepare_context', 'remember', 'search_memory'] |