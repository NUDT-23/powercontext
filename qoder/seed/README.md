# Seed 语料

`papers.json` 包含 20 篇 arXiv 公开论文的元数据与摘要（标题、作者、年份、摘要、arXiv ID），用于演示混合检索与综述生成，不包含受限全文。

- 来源：arXiv API（`https://export.arxiv.org/api/query`），按 “LLM agents” 与 “causal inference” 相关性检索。
- 使用仅限竞赛演示；引用时请注明 arXiv 与原作者。
- 重新抓取：`python scripts/fetch_arxiv_seed.py`（可选，需要网络）。
