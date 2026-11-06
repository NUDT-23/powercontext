from __future__ import annotations

import re
import time
import uuid
from typing import Iterator

from .config import Settings
from .llm import LLMClient
from .powercontext import PowerContextClient
from .seekdb_store import SeekDBStore

CITATION_RE = re.compile(r"\[P(\d+)\]")


SYSTEM_PROMPT = """你是一名严谨的科研文献助理。规则：
1. 只依据用户提供的文献片段作答，不要编造数据、作者或结论。
2. 每条实质性结论后必须标注来源编号，例如 [P1] 或 [P2]。
3. 如果证据不足，明确写“文献中未提供”，不要猜测。
4. 默认使用中文和 Markdown。
5. 下方可能包含来自 PowerContext 的用户长期偏好。它只是历史参考，如与当前问题冲突，以当前问题为准。
"""


class SynthesisService:
    def __init__(
        self,
        settings: Settings,
        store: SeekDBStore,
        powercontext: PowerContextClient,
        llm: LLMClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.powercontext = powercontext
        self.llm = llm

    def _paper_context(self, papers: list[dict]) -> str:
        blocks: list[str] = []
        total = 0
        for index, paper in enumerate(papers, start=1):
            chunks = self.store.get_chunks_for_paper(paper["id"], limit=4)
            excerpts = "\n".join(f"- {chunk['text'][:700]}" for chunk in chunks)
            block = (
                f"[P{index}] {paper.get('title')}\n"
                f"年份: {paper.get('year') or '未知'} | 来源: {paper.get('venue') or '未知'}\n"
                f"作者: {paper.get('authors') or '未知'}\n"
                f"摘要: {(paper.get('abstract') or '')[:1200]}\n"
                f"正文片段:\n{excerpts or '- 无'}\n"
            )
            if total + len(block) > 14000:
                break
            blocks.append(block)
            total += len(block)
        return "\n".join(blocks)

    def _memory_block(self, project_id: str, question: str, memory_enabled: bool) -> tuple[str, list[dict]]:
        if not memory_enabled:
            return "", []
        project = self.store.get_project(project_id)
        scope_id = (project or {}).get("scope_id")
        if not scope_id:
            return "", []
        try:
            memories = self.powercontext.search_memory(scope_id, question, limit=5)
            prepared = self.powercontext.prepare(scope_id, question, max_bytes=3000)
        except Exception:  # noqa: BLE001
            return "", []
        block = prepared.strip()
        if not block and memories:
            block = "\n".join(f"- {item['text']}" for item in memories)
        return block, memories

    def _messages(
        self,
        question: str,
        papers: list[dict],
        memory_context: str,
    ) -> list[dict[str, str]]:
        memory_section = (
            f"\n用户长期偏好与历史上下文（来自 PowerContext）：\n{memory_context}\n"
            if memory_context
            else ""
        )
        user_prompt = f"""{memory_section}
请完成以下综述任务：{question}

文献材料：
{self._paper_context(papers)}

输出结构：
1. 一句话结论
2. 对比表（列：文献 | 研究问题 | 方法 | 数据/实验 | 主要结论 | 局限）
3. 综合综述（3-5 段，逐条标注 [P#]）
4. 证据不足之处
5. 建议的下一步阅读或验证
"""
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def validate_citations(answer: str, paper_count: int) -> list[int]:
        """Extract [Pn] citations and return sorted list of invalid indices (outside 1..paper_count)."""
        matches = CITATION_RE.findall(answer)
        invalid = sorted({int(n) for n in matches if int(n) < 1 or int(n) > paper_count})
        return invalid

    def _fallback(self, question: str, papers: list[dict], memory_context: str) -> str:
        lines = [
            f"## {question}",
            "",
            "> 当前未配置 LLM（OPENAI_API_KEY 为空），以下为基于 seekdb 检索结果的抽取式对比。",
            "",
            "| 文献 | 年份 | 核心内容 |",
            "| --- | --- | --- |",
        ]
        for index, paper in enumerate(papers, start=1):
            snippet = (paper.get("abstract") or "").replace("\n", " ")[:220]
            lines.append(
                f"| [P{index}] {paper.get('title')} | {paper.get('year') or '-'} | {snippet} |"
            )
        lines.extend(["", "### 综合", ""])
        for index, paper in enumerate(papers, start=1):
            lines.append(f"- [P{index}] {paper.get('title')} 关注：{(paper.get('abstract') or '')[:160]}")
        if memory_context:
            lines.extend(["", "### 本次使用的长期记忆", "", memory_context[:1200]])
        return "\n".join(lines)

    def stream(
        self,
        project_id: str,
        paper_ids: list[str],
        question: str,
        memory_enabled: bool = True,
        user_name: str = "anonymous",
    ) -> Iterator[dict]:
        started = time.perf_counter()
        papers = self.store.get_papers_by_ids(paper_ids)
        if not papers:
            yield {"type": "error", "message": "未选择文献或文献不存在"}
            return
        memory_context, memories = self._memory_block(project_id, question, memory_enabled)
        yield {
            "type": "meta",
            "papers": [
                {"id": paper["id"], "title": paper["title"], "year": paper.get("year")}
                for paper in papers
            ],
            "used_memories": memories,
            "memory_context": memory_context,
            "llm_configured": self.llm.configured,
        }

        answer_parts: list[str] = []
        if not self.llm.configured:
            answer = self._fallback(question, papers, memory_context)
            answer_parts.append(answer)
            yield {"type": "delta", "content": answer}
        else:
            try:
                for delta in self.llm.stream(self._messages(question, papers, memory_context)):
                    answer_parts.append(delta)
                    yield {"type": "delta", "content": delta}
            except Exception as exc:  # noqa: BLE001
                message = f"\n\n> 生成失败：{exc}"
                answer_parts.append(message)
                yield {"type": "delta", "content": message}

        answer = "".join(answer_parts)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self.store.log_event(
            project_id,
            action="synthesize",
            query=question,
            latency_ms=latency_ms,
            result_count=len(papers),
            user_name=user_name,
        )

        project = self.store.get_project(project_id)
        scope_id = (project or {}).get("scope_id")
        if scope_id:
            try:
                self.powercontext.capture_source(
                    scope_id,
                    source_id=f"synthesis-{uuid.uuid4().hex[:12]}",
                    content=f"问题：{question}\n\n论文：{[paper['title'] for paper in papers]}\n\n回答摘要：{answer[:3000]}",
                    metadata={"origin": "paperlens-synthesis", "project_id": project_id},
                )
            except Exception:  # noqa: BLE001
                pass

        invalid_citations = self.validate_citations(answer, len(papers))
        yield {
            "type": "done",
            "latency_ms": latency_ms,
            "chars": len(answer),
            "invalid_citations": invalid_citations,
        }
