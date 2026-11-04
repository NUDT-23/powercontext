# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Prepare final, bounded context from approved Artifact evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import chain
from typing import TypeVar

from powercontext.artifacts import ArtifactAddress, ArtifactRef
from powercontext.builtin.artifacts.experience import Experience, ExperienceSearchHit, render_experience
from powercontext.builtin.artifacts.memory.models import MemoryCitation, MemoryHit
from powercontext.builtin.artifacts.profile.models import Profile
from powercontext.builtin.artifacts.topic_memory import TopicMemory, TopicMemorySearchHit
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_code import (
    CodeEvidenceRef,
    PreparedCodeCandidate,
    assemble_code,
)
from powercontext.builtin.runtime.prepared_text import (
    TRUST_POLICY,
    ContextTextItem,
    fit_context_text_item,
    render_context_text,
)
from powercontext.builtin.runtime.recall_sufficiency import RecallBudgetView

_MIN_TRUNCATED_CONTENT_BYTES = 64
_ELLIPSIS = "…"
_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_Item = TypeVar("_Item")


@dataclass(frozen=True)
class _PreparedContextEntry:
    origin: PreparedContextOrigin
    kind: str
    citation: dict[str, object]
    content: str
    truncated: bool


@dataclass(frozen=True)
class _EntryFit:
    """One fit attempt on the non-assembly path: the entry that fitted, or why none did.

    The two drop reasons are disjoint and mirror the assembly path's
    :class:`~powercontext.builtin.runtime.prepared_text.FitOutcome`. An entry is dropped
    *below the minimum truncated content* when a shorter rendering exists and fits but is too
    short to be an honest delivery; it is dropped *with no fitting truncation* when no
    shortened rendering fits at all.
    """

    entry: _PreparedContextEntry | None = None
    dropped_below_min_bytes: bool = False
    dropped_no_fitting_truncation: bool = False


@dataclass(frozen=True)
class PreparedContextOmissions:
    """Aggregate counts of the items the byte budget omitted in one build.

    Every count is a per-call aggregate, never per-entry attribution and never a verdict about
    an entry: an entry losing to the budget is not a negative result about that entry.

    ``dropped_items`` is the sum of its two sub-counts, so "the budget could not fit this
    item" can be told apart from "this item was too short to truncate into the remaining
    space". A single merged counter would misreport the second cause as the first.
    """

    truncated_items: int = 0
    dropped_items: int = 0
    dropped_below_min_bytes: int = 0
    dropped_no_fitting_truncation: int = 0


@dataclass(frozen=True)
class PreparedContextBuild:
    """Final public context and the exact origins selected to produce it.

    ``omissions`` is always filled by the Builder. The RFC 1560 recall trace is deliberately
    **not** a field here: ``ScopedContextApplication._prepare`` returns ``build.context`` and
    discards the rest, so such a field would have no production observer. The trace is
    delivered through the Runtime's optional ``RecallEffortSink`` instead.
    """

    context: PreparedContext
    origins: tuple[PreparedContextOrigin, ...]
    omissions: PreparedContextOmissions = PreparedContextOmissions()
    code_origins: tuple[CodeEvidenceRef, ...] = ()
    fragments: tuple["PreparedContextFragment", ...] = ()


@dataclass(frozen=True)
class MemoryEntryAddress:
    """Identify one exact Memory entry version across Scope boundaries."""

    memory: ArtifactAddress
    entry_id: str
    entry_version_id: str


@dataclass(frozen=True)
class PreparedContextFragment:
    """One exact substring of a Memory entry selected as evidence for a query.

    ``start``/``end`` are half-open Python character coordinates into the entry text of the
    exact version identified by ``address``; ``text`` is that substring, unmodified. Several
    fragments of one entry are separate verbatim excerpts, never rewritten evidence.
    """

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


PreparedContextOrigin = MemoryCitation | ArtifactRef | MemoryEntryAddress | ArtifactAddress


@dataclass(frozen=True)
class PreparedMemoryCandidates:
    """Memory candidates read from one Scope."""

    scope_id: str
    memory_ref: ArtifactRef | None = None
    hits: tuple[MemoryHit, ...] = ()


@dataclass(frozen=True)
class PreparedExperienceCandidates:
    """Experience candidates read from one Scope."""

    scope_id: str
    hits: tuple[ExperienceSearchHit, ...] = ()


@dataclass(frozen=True)
class PreparedProfileCandidate:
    """The latest committed Profile snapshot read from one Scope."""

    scope_id: str
    profile: Profile


class PreparedContextBuilder:
    """Select and render final context without I/O, persistence, or reranking."""

    memory_candidate_limit = 16
    topic_memory_candidate_limit = 8
    experience_candidate_limit = 8
    candidate_limit = memory_candidate_limit
    entry_limit = 8
    topic_memory_entry_limit = 8
    experience_entry_limit = 2
    max_entry_content_bytes = 2000
    _text_entry_limit: int | None = None

    def empty(self) -> PreparedContext:
        return PreparedContext(status="empty", content=None, content_bytes=0)

    def build(
        self,
        *,
        request: PrepareContextRequest,
        scope_id: str | None = None,
        memory_ref: ArtifactRef | None = None,
        hits: Sequence[MemoryHit] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_hits: Sequence[ExperienceSearchHit] = (),
    ) -> PreparedContext:
        return self.build_result(
            request=request,
            scope_id=scope_id,
            memory_ref=memory_ref,
            hits=hits,
            topic_memory_hits=topic_memory_hits,
            experience_hits=experience_hits,
        ).context

    def build_result(
        self,
        *,
        request: PrepareContextRequest,
        scope_id: str | None = None,
        memory_ref: ArtifactRef | None = None,
        hits: Sequence[MemoryHit] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_hits: Sequence[ExperienceSearchHit] = (),
    ) -> PreparedContextBuild:
        return self.build_scopes_result(
            request=request,
            current_scope_id=scope_id,
            memory_candidates=(
                PreparedMemoryCandidates(scope_id=scope_id or "", memory_ref=memory_ref, hits=tuple(hits)),
            ),
            experience_candidates=(PreparedExperienceCandidates(scope_id=scope_id or "", hits=tuple(experience_hits)),),
            topic_memory_hits=topic_memory_hits,
        )

    def build_scopes_result(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_candidates: Sequence[PreparedExperienceCandidates] = (),
        profile_candidates: Sequence[PreparedProfileCandidate] = (),
        code_candidates: Sequence[PreparedCodeCandidate] = (),
    ) -> PreparedContextBuild:
        if request.evidence_selection:
            return self._select_evidence(request=request, memory_candidates=memory_candidates)
        if request.include_code:

            def historical(history_request: PrepareContextRequest, entries: int) -> PreparedContextBuild:
                builder = PreparedContextBuilder()
                builder.entry_limit = entries
                builder._text_entry_limit = entries if entries < self.entry_limit else None
                return builder.build_scopes_result(
                    request=history_request.model_copy(update={"include_code": False}),
                    current_scope_id=current_scope_id,
                    memory_candidates=memory_candidates,
                    topic_memory_hits=topic_memory_hits,
                    experience_candidates=experience_candidates,
                    profile_candidates=profile_candidates,
                )

            return assemble_code(request, code_candidates, self.entry_limit, historical)

        if sum(len(candidates.hits) for candidates in memory_candidates) > self.memory_candidate_limit:
            raise PreparedContextInvariantError("memory-candidate-limit")
        if len(topic_memory_hits) > self.topic_memory_candidate_limit:
            raise PreparedContextInvariantError("topic-memory-candidate-limit")
        if sum(len(candidates.hits) for candidates in experience_candidates) > self.experience_candidate_limit:
            raise PreparedContextInvariantError("experience-candidate-limit")

        content, origins, omissions = self._select_entries(
            request=request,
            current_scope_id=current_scope_id,
            memory_candidates=memory_candidates,
            experience_candidates=experience_candidates,
            profile_candidates=profile_candidates,
            topic_memory_hits=topic_memory_hits,
        )
        if content is None:
            return PreparedContextBuild(context=self.empty(), origins=(), omissions=omissions)
        content_bytes = len(content.encode("utf-8"))
        # The assembly path is bounded by construction (every fitted item is measured against
        # `max_bytes`), so the ceiling check belongs to the non-assembly renderer only.
        if request.assembly is None and content_bytes > request.max_bytes:
            raise PreparedContextInvariantError("output-budget")
        return PreparedContextBuild(
            context=PreparedContext(status="ready", content=content, content_bytes=content_bytes),
            origins=origins,
            omissions=omissions,
        )

    def probe_budget(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates] = (),
        topic_memory_hits: Sequence[TopicMemorySearchHit] = (),
        experience_candidates: Sequence[PreparedExperienceCandidates] = (),
        profile_candidates: Sequence[PreparedProfileCandidate] = (),
    ) -> RecallBudgetView:
        """Report what the byte budget does to one candidate set, without delivering it.

        This is the RFC 1560 *budget probe*: one pass of this Builder's own pure selection and
        rendering code, keeping only the counters and discarding the rendered output. It lets
        the gate tell budget-limited thinness from recall-limited thinness.

        Pure and side-effect free: no I/O, no persistence, nothing reported to any sink, and
        the same inputs as :meth:`build_scopes_result` are guaranteed to yield the same
        counters because both go through :meth:`_select_entries`.
        """

        content, origins, omissions = self._select_entries(
            request=request,
            current_scope_id=current_scope_id,
            memory_candidates=memory_candidates,
            experience_candidates=experience_candidates,
            profile_candidates=profile_candidates,
            topic_memory_hits=topic_memory_hits,
        )
        content_bytes = 0 if content is None else len(content.encode("utf-8"))
        return RecallBudgetView(
            max_bytes=request.max_bytes,
            delivered_items=len(origins),
            truncated_items=omissions.truncated_items,
            dropped_items=omissions.dropped_items,
            unused_bytes=max(0, request.max_bytes - content_bytes),
        )

    def _select_evidence(
        self,
        *,
        request: PrepareContextRequest,
        memory_candidates: Sequence[PreparedMemoryCandidates],
    ) -> PreparedContextBuild:
        """Select exact entry substrings as query evidence under the byte budget.

        The evidence-selection mode of RFC 1565: candidates are already recalled Memory
        entries, and this path picks verbatim fragments out of them for ``request.query``.
        Fragments keep exact origins and character coordinates, and the budget counts the
        whole rendered output (trust policy, envelope, JSON and citations), not just the
        excerpt bytes. Topic, Experience, Profile and Code candidates are out of scope here;
        the default prepare path is untouched while the mode is off.
        """

        if sum(len(candidates.hits) for candidates in memory_candidates) > self.memory_candidate_limit:
            raise PreparedContextInvariantError("memory-candidate-limit")
        entries = _evidence_entries(memory_candidates)
        chosen = _select_evidence_fragments(query=request.query, max_bytes=request.max_bytes, entries=entries)
        fragments = tuple(
            PreparedContextFragment(
                address=MemoryEntryAddress(
                    memory=ArtifactAddress(scope_id=entry.scope_id, artifact=entry.memory_ref),
                    entry_id=entry.entry_id,
                    entry_version_id=entry.entry_version_id,
                ),
                start=start,
                end=end,
                text=entry.text[start:end],
            )
            for entry, start, end in chosen
        )
        if not fragments:
            return PreparedContextBuild(context=self.empty(), origins=(), omissions=PreparedContextOmissions())
        content = _render_evidence(chosen)
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > request.max_bytes:
            raise PreparedContextInvariantError("output-budget")
        return PreparedContextBuild(
            context=PreparedContext(status="ready", content=content, content_bytes=content_bytes),
            origins=tuple(fragment.address for fragment in fragments),
            omissions=PreparedContextOmissions(),
            fragments=fragments,
        )

    def _select_entries(
        self,
        *,
        request: PrepareContextRequest,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
        topic_memory_hits: Sequence[TopicMemorySearchHit],
        experience_candidates: Sequence[PreparedExperienceCandidates],
        profile_candidates: Sequence[PreparedProfileCandidate],
    ) -> tuple[str | None, tuple[PreparedContextOrigin, ...], PreparedContextOmissions]:
        """Run one complete pure selection pass and render it.

        Returns ``(content, origins, omissions)``; ``content`` is ``None`` exactly when nothing
        was selected, which is the empty-result case for both paths. This is the single
        selection path shared by :meth:`build_scopes_result` and :meth:`probe_budget`, so the
        probe's counters always describe the selection the build would actually perform.
        """

        if request.assembly is not None:
            return self._select_text(
                request,
                current_scope_id=current_scope_id,
                memory_candidates=memory_candidates,
                experience_candidates=experience_candidates,
                profile_candidates=profile_candidates,
                topic_memory_hits=topic_memory_hits,
            )

        memory_entries = _interleave_groups(
            tuple(
                self._memory_entries(
                    candidates.memory_ref,
                    candidates.hits,
                    scope_id=None if candidates.scope_id == current_scope_id else candidates.scope_id or None,
                )
                for candidates in memory_candidates
            )
        )
        topic_memory_entries = self._topic_memory_entries(topic_memory_hits)
        experience_entries = _interleave_groups(
            tuple(
                self._experience_entries(
                    candidates.hits,
                    scope_id=None if candidates.scope_id == current_scope_id else candidates.scope_id or None,
                )
                for candidates in experience_candidates
            )
        )[: self.experience_entry_limit]
        entries, omissions = self._fit_entries(request, memory_entries, topic_memory_entries, experience_entries)
        if not entries:
            return None, (), omissions
        return _render(entries), tuple(entry.origin for entry in entries), omissions

    def _select_text(
        self,
        request: PrepareContextRequest,
        *,
        current_scope_id: str | None,
        memory_candidates: Sequence[PreparedMemoryCandidates],
        experience_candidates: Sequence[PreparedExperienceCandidates],
        profile_candidates: Sequence[PreparedProfileCandidate],
        topic_memory_hits: Sequence[TopicMemorySearchHit],
    ) -> tuple[str | None, tuple[PreparedContextOrigin, ...], PreparedContextOmissions]:
        assembly = request.assembly
        if assembly is None:
            raise PreparedContextInvariantError("text-assembly-missing")
        included: list[ContextTextItem] = []
        origins: list[PreparedContextOrigin] = []
        truncated_items = 0
        dropped_below_min_bytes = 0
        dropped_no_fitting_truncation = 0
        for section in assembly.sections:
            # Unfilled earlier sections leave their capacity available to later ones.
            limit = (
                section.limit
                if self._text_entry_limit is None
                else min(section.limit, self._text_entry_limit - len(included))
            )
            if section.family == "profile":
                entries = self._profile_entries(profile_candidates)
            elif section.family == "topic-memory":
                entries = self._topic_memory_entries(topic_memory_hits, scope_id=current_scope_id)
            else:
                groups = (
                    tuple(
                        tuple(
                            self._memory_entries(group.memory_ref, (hit,), scope_id=group.scope_id)
                            for hit in group.hits
                        )
                        for group in memory_candidates
                    )
                    if section.family == "memory"
                    else tuple(
                        tuple(self._experience_entries((hit,), scope_id=group.scope_id) for hit in group.hits)
                        for group in experience_candidates
                    )
                )
                entries = tuple(chain.from_iterable(_interleave_groups(groups)))
            seen: set[tuple[str, str, str, int, str | None, str | None]] = set()
            rank = 0
            selected_count = 0
            for entry in entries:
                if selected_count >= limit:
                    break
                item = _text_item(entry)
                artifact = item.artifact
                identity = (
                    artifact.scope_id,
                    artifact.artifact.family,
                    artifact.artifact.artifact_id,
                    artifact.artifact.revision,
                    item.entry_id,
                    item.entry_version_id,
                )
                if identity in seen or not item.content.strip():
                    continue
                seen.add(identity)
                rank += 1
                outcome = fit_context_text_item(included, replace(item, recall_rank=rank), assembly, request.max_bytes)
                if outcome.item is None:
                    dropped_below_min_bytes += int(outcome.dropped_below_min_bytes)
                    dropped_no_fitting_truncation += int(outcome.dropped_no_fitting_truncation)
                    continue
                fitted = outcome.item
                included.append(fitted)
                origins.append(entry.origin)
                selected_count += 1
                truncated_items += int(fitted.truncated)
        omissions = PreparedContextOmissions(
            truncated_items=truncated_items,
            dropped_items=dropped_below_min_bytes + dropped_no_fitting_truncation,
            dropped_below_min_bytes=dropped_below_min_bytes,
            dropped_no_fitting_truncation=dropped_no_fitting_truncation,
        )
        if not included:
            return None, (), omissions
        content = render_context_text(included, assembly)
        return content, tuple(origins), omissions

    def _profile_entries(self, candidates: Sequence[PreparedProfileCandidate]) -> tuple[_PreparedContextEntry, ...]:
        entries = []
        for candidate in candidates:
            origin = ArtifactAddress(scope_id=candidate.scope_id, artifact=candidate.profile.as_ref())
            entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="profile",
                    citation={"artifact": origin.model_dump(mode="json")},
                    content=candidate.profile.content.content,
                    truncated=False,
                )
            )
        return tuple(entries)

    def _memory_entries(
        self,
        memory_ref: ArtifactRef | None,
        hits: Sequence[MemoryHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        if hits and memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        memory_entries: list[_PreparedContextEntry] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            if hit.memory_ref != memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")

            citation_key = (hit.entry_id, hit.entry_version_id)
            if citation_key in seen:
                continue
            seen.add(citation_key)
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            origin: PreparedContextOrigin = citation
            rendered_citation = citation.model_dump(mode="json")
            if scope_id is not None:
                memory = ArtifactAddress(scope_id=scope_id, artifact=hit.memory_ref)
                origin = MemoryEntryAddress(
                    memory=memory,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
                rendered_citation = {
                    "memory": memory.model_dump(mode="json"),
                    "entry_id": hit.entry_id,
                    "entry_version_id": hit.entry_version_id,
                }
            memory_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="memory",
                    citation=rendered_citation,
                    content=hit.text,
                    truncated=False,
                )
            )
        return tuple(memory_entries)

    def _topic_memory_entries(
        self,
        hits: Sequence[TopicMemorySearchHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        topic_entries: list[_PreparedContextEntry] = []
        seen_topics: set[tuple[str, int]] = set()
        for hit in hits:
            if hit.artifact_ref.family != TopicMemory.family:
                raise PreparedContextInvariantError("topic-memory-family-mismatch")
            identity = (hit.artifact_ref.artifact_id, hit.artifact_ref.revision)
            if identity in seen_topics:
                continue
            seen_topics.add(identity)
            if len(topic_entries) >= self.topic_memory_entry_limit:
                break
            content = {"title": hit.title, "summary": hit.summary}
            if hit.snippet is not None:
                content["snippet"] = hit.snippet
            origin: PreparedContextOrigin = hit.artifact_ref
            citation = {"artifact_ref": hit.artifact_ref.model_dump(mode="json")}
            body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            if scope_id is not None:
                origin = ArtifactAddress(scope_id=scope_id, artifact=hit.artifact_ref)
                citation = {"artifact": origin.model_dump(mode="json")}
                body = "\n\n".join(f"{label.capitalize()}: {value}" for label, value in content.items())
            topic_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="topic-memory",
                    citation=citation,
                    content=body,
                    truncated=False,
                )
            )
        return tuple(topic_entries)

    def _experience_entries(
        self,
        hits: Sequence[ExperienceSearchHit],
        *,
        scope_id: str | None = None,
    ) -> tuple[_PreparedContextEntry, ...]:
        experience_entries: list[_PreparedContextEntry] = []
        seen_experiences: set[tuple[str, int]] = set()
        for hit in hits:
            if hit.artifact_ref.family != Experience.family:
                raise PreparedContextInvariantError("experience-family-mismatch")
            identity = (hit.artifact_ref.artifact_id, hit.artifact_ref.revision)
            if identity in seen_experiences:
                continue
            seen_experiences.add(identity)
            origin: PreparedContextOrigin = hit.artifact_ref
            rendered_citation: dict[str, object] = {"artifact_ref": hit.artifact_ref.model_dump(mode="json")}
            if scope_id is not None:
                origin = ArtifactAddress(scope_id=scope_id, artifact=hit.artifact_ref)
                rendered_citation = {"artifact": origin.model_dump(mode="json")}
            experience_entries.append(
                _PreparedContextEntry(
                    origin=origin,
                    kind="experience",
                    citation=rendered_citation,
                    content=render_experience(hit.content),
                    truncated=False,
                )
            )
        return tuple(experience_entries)

    def _fit_entries(
        self,
        request: PrepareContextRequest,
        memory_entries: Sequence[_PreparedContextEntry],
        topic_memory_entries: Sequence[_PreparedContextEntry],
        experience_entries: Sequence[_PreparedContextEntry],
    ) -> tuple[tuple[_PreparedContextEntry, ...], PreparedContextOmissions]:
        entries: list[_PreparedContextEntry] = []
        truncated_items = 0
        dropped_below_min_bytes = 0
        dropped_no_fitting_truncation = 0
        for candidate in _interleave(memory_entries, topic_memory_entries, experience_entries):
            if len(entries) >= self.entry_limit:
                break
            fit = self._fit_entry(
                entries,
                origin=candidate.origin,
                kind=candidate.kind,
                citation=candidate.citation,
                text=candidate.content,
                max_bytes=request.max_bytes,
            )
            if fit.entry is None:
                dropped_below_min_bytes += int(fit.dropped_below_min_bytes)
                dropped_no_fitting_truncation += int(fit.dropped_no_fitting_truncation)
                continue
            entries.append(fit.entry)
            if fit.entry.truncated:
                truncated_items += 1
        return tuple(entries), PreparedContextOmissions(
            truncated_items=truncated_items,
            dropped_items=dropped_below_min_bytes + dropped_no_fitting_truncation,
            dropped_below_min_bytes=dropped_below_min_bytes,
            dropped_no_fitting_truncation=dropped_no_fitting_truncation,
        )

    def _fit_entry(
        self,
        entries: Sequence[_PreparedContextEntry],
        *,
        origin: PreparedContextOrigin,
        kind: str,
        citation: dict[str, object],
        text: str,
        max_bytes: int,
    ) -> _EntryFit:
        """Fit one entry into the remaining budget, reporting why it was dropped if it was.

        The two ``None`` paths of the original code are kept apart: ``below-min-bytes`` means a
        shorter rendering exists and fits but is too short to deliver honestly, while
        ``no-fitting-truncation`` means no shortened rendering fitted at all.
        """

        source_bytes = len(text.encode("utf-8"))
        entry_budget = min(source_bytes, self.max_entry_content_bytes)
        candidate = _PreparedContextEntry(
            origin=origin,
            kind=kind,
            citation=citation,
            content=text if source_bytes <= entry_budget else _truncate_utf8(text, entry_budget),
            truncated=source_bytes > entry_budget,
        )
        if _rendered_bytes((*entries, candidate)) <= max_bytes:
            return _EntryFit(entry=candidate)
        if source_bytes < _MIN_TRUNCATED_CONTENT_BYTES:
            return _EntryFit(dropped_below_min_bytes=True)

        lower = _MIN_TRUNCATED_CONTENT_BYTES
        upper = min(entry_budget, source_bytes - 1)
        best: _PreparedContextEntry | None = None
        while lower <= upper:
            byte_budget = (lower + upper) // 2
            candidate = _PreparedContextEntry(
                origin=origin,
                kind=kind,
                citation=citation,
                content=_truncate_utf8(text, byte_budget),
                truncated=True,
            )
            if len(candidate.content.encode("utf-8")) < _MIN_TRUNCATED_CONTENT_BYTES:
                lower = byte_budget + 1
                continue
            if _rendered_bytes((*entries, candidate)) <= max_bytes:
                best = candidate
                lower = byte_budget + 1
            else:
                upper = byte_budget - 1
        if best is None:
            return _EntryFit(dropped_no_fitting_truncation=True)
        return _EntryFit(entry=best)


_EVIDENCE_TOKEN_RE = re.compile(r"[a-z]+|\d+|[一-鿿]+")
_EVIDENCE_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_EVIDENCE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "so", "yet", "of", "to", "in", "on", "at",
    "by", "as", "for", "with", "from", "into", "onto", "upon", "over", "under", "between",
    "among", "during", "through", "across", "against", "within", "without", "via", "per",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "done",
    "have", "has", "had", "having", "will", "would", "shall", "should", "can", "could",
    "may", "might", "must", "this", "that", "these", "those", "it", "its", "they", "them",
    "their", "we", "our", "us", "you", "your", "he", "she", "his", "her", "him", "not",
    "no", "than", "then", "too", "very", "also", "just", "only", "such", "some", "any",
    "all", "both", "each", "other", "others", "more", "most", "less", "least", "same",
    "own", "how", "what", "which", "who", "whom", "whose", "when", "where", "why", "there",
    "here", "about", "after", "before", "up", "down", "out", "off", "again", "further",
    "while", "because", "if", "whether",
})
_EVIDENCE_LONG_SENTENCE_CHARS = 260
_EVIDENCE_CHUNK_CHARS = 200
_EVIDENCE_UNIT_BASE_COST = 100
_EVIDENCE_WINDOW_OVERHEAD_BYTES = 260


@dataclass(frozen=True)
class _EvidenceSentence:
    """One selectable verbatim unit with half-open coordinates and matched stems."""

    start: int
    end: int
    stems: frozenset[str]


@dataclass(frozen=True)
class _EvidenceEntryData:
    """One candidate Memory entry flattened for the offline selection pass."""

    scope_id: str
    memory_ref: ArtifactRef
    entry_id: str
    entry_version_id: str
    rank: int
    text: str
    sentences: tuple[_EvidenceSentence, ...]


def _evidence_stem(token: str) -> str:
    """Fold inflectional suffixes so claim wording can match evidence wording."""

    if token.isdigit():
        return token
    for suffix, replacement in (
        ("ies", "y"),
        ("sses", "ss"),
        ("ches", "ch"),
        ("shes", "sh"),
        ("xes", "x"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("ly", ""),
        ("s", ""),
        ("e", ""),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)] + replacement
    return token


def _evidence_query_stems(query: str) -> frozenset[str]:
    return frozenset(
        _evidence_stem(token)
        for token in _EVIDENCE_TOKEN_RE.findall(query.casefold())
        if token not in _EVIDENCE_STOPWORDS
    )


def _evidence_sentence_bounds(text: str) -> list[tuple[int, int]]:
    """Half-open sentence units with trimmed boundaries, keeping exact coordinates."""

    bounds: list[tuple[int, int]] = []
    cursor = 0
    for gap in _EVIDENCE_SENTENCE_RE.finditer(text):
        bounds.append((cursor, gap.start()))
        cursor = gap.end()
    bounds.append((cursor, len(text)))
    trimmed: list[tuple[int, int]] = []
    for start, end in bounds:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            trimmed.append((start, end))
    return trimmed


def _evidence_split_long(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split oversized units at word boundaries so any budget can admit a piece."""

    if end - start <= _EVIDENCE_LONG_SENTENCE_CHARS:
        return [(start, end)]
    pieces: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > _EVIDENCE_LONG_SENTENCE_CHARS:
        limit = cursor + _EVIDENCE_CHUNK_CHARS
        window = text[cursor:limit]
        cut = window.rfind(" ")
        piece_end = limit if cut < _EVIDENCE_CHUNK_CHARS // 2 else cursor + cut
        while piece_end > cursor and text[piece_end - 1].isspace():
            piece_end -= 1
        if piece_end > cursor:
            pieces.append((cursor, piece_end))
        cursor = max(cursor + 1, piece_end)
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        pieces.append((cursor, end))
    return [piece for piece in pieces if piece[0] < piece[1]]


def _evidence_sentences(text: str) -> tuple[_EvidenceSentence, ...]:
    sentences: list[_EvidenceSentence] = []
    for start, end in _evidence_sentence_bounds(text):
        for piece_start, piece_end in _evidence_split_long(text, start, end):
            body = text[piece_start:piece_end]
            stems = frozenset(
                _evidence_stem(token)
                for token in _EVIDENCE_TOKEN_RE.findall(body.casefold())
                if token not in _EVIDENCE_STOPWORDS
            )
            sentences.append(_EvidenceSentence(start=piece_start, end=piece_end, stems=stems))
    return tuple(sentences)


def _evidence_entries(memory_candidates: Sequence[PreparedMemoryCandidates]) -> tuple[_EvidenceEntryData, ...]:
    """Flatten candidate groups into ranked entries, keeping the builder invariants."""

    entries: list[_EvidenceEntryData] = []
    seen: set[tuple[str, str, str]] = set()
    rank = 0
    for candidates in memory_candidates:
        if candidates.hits and candidates.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        for hit in candidates.hits:
            if hit.memory_ref != candidates.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            identity = (candidates.scope_id, hit.entry_id, hit.entry_version_id)
            if identity in seen:
                continue
            seen.add(identity)
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            entries.append(
                _EvidenceEntryData(
                    scope_id=candidates.scope_id,
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                    rank=rank,
                    text=hit.text,
                    sentences=_evidence_sentences(hit.text),
                )
            )
            rank += 1
    return tuple(entries)


def _index_runs(ordered: Sequence[int]) -> tuple[tuple[int, int], ...]:
    runs: list[tuple[int, int]] = []
    for index in ordered:
        if runs and index == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], index)
        else:
            runs.append((index, index))
    return tuple(runs)


def _select_evidence_fragments(
    *,
    query: str,
    max_bytes: int,
    entries: tuple[_EvidenceEntryData, ...],
) -> tuple[tuple[_EvidenceEntryData, int, int], ...]:
    """Greedy query-driven selection of verbatim entry intervals under the budget.

    The byte budget is dominated by per-window citation overhead, so selection
    concentrates instead of scattering: one density queue ranks every candidate move -
    extending an existing run costs the unit's bytes, opening a new window also pays the
    citation overhead - and applies the best score-per-byte move that still fits.
    Extensions therefore outrank distant seeds and the budget piles onto contiguous
    spans, which is where annotated evidence lives. Sentence scores come from stemmed
    query overlap weighted by document frequency, with the opening unit (usually a
    title echoing the claim wording) counting half. Once every scored move is spent,
    leftover bytes grow run boundaries; if nothing scored at all, the top-ranked entry
    still contributes its first unit. Every acceptance is measured against the exact
    rendered output bytes, and a refusal stays final because the rendering only ever
    grows.
    """

    if not entries:
        return ()
    query_stems = _evidence_query_stems(query)
    document_frequency: Counter[str] = Counter()
    for stem in query_stems:
        document_frequency[stem] = sum(
            1 for entry in entries if any(stem in sentence.stems for sentence in entry.sentences)
        )
    weights = {
        stem: 2.0 if count <= 1 else 1.4 if count == 2 else 1.0
        for stem, count in document_frequency.items()
    }
    raw_scores: dict[tuple[int, int], float] = {}
    for entry_index, entry in enumerate(entries):
        for sentence_index, sentence in enumerate(entry.sentences):
            raw_scores[(entry_index, sentence_index)] = sum(
                weight for stem, weight in weights.items() if stem in sentence.stems
            )
    priority = sorted(
        range(len(entries)),
        key=lambda entry_index: (
            -sum(
                sorted(
                    (raw_scores[(entry_index, s)] for s in range(len(entries[entry_index].sentences))),
                    reverse=True,
                )[:3]
            ),
            -sum(raw_scores[(entry_index, s)] for s in range(len(entries[entry_index].sentences))),
            entries[entry_index].rank,
        ),
    )
    priority_rank = {entry_index: rank for rank, entry_index in enumerate(priority)}

    def unit_bytes(key: tuple[int, int]) -> int:
        sentence = entries[key[0]].sentences[key[1]]
        return sentence.end - sentence.start

    scores = {
        key: (0.5 if key[1] == 0 else 1.0) * raw_score for key, raw_score in raw_scores.items()
    }
    selected: dict[int, set[int]] = {entry_index: set() for entry_index in range(len(entries))}
    blocked: set[tuple[int, int]] = set()

    def chosen() -> tuple[tuple[_EvidenceEntryData, int, int], ...]:
        fragments: list[tuple[_EvidenceEntryData, int, int]] = []
        for entry_index, entry in enumerate(entries):
            indices = sorted(selected[entry_index])
            if not indices:
                continue
            for run_start, run_end in _index_runs(indices):
                start = entry.sentences[run_start].start
                end = entry.sentences[run_end].end
                while start < end and entry.text[start].isspace():
                    start += 1
                while end > start and entry.text[end - 1].isspace():
                    end -= 1
                if start < end:
                    fragments.append((entry, start, end))
        return tuple(fragments)

    def rendered_bytes() -> int:
        fragments = chosen()
        if not fragments:
            return 0
        return len(_render_evidence(fragments).encode("utf-8"))

    def apply(entry_index: int, sentence_index: int) -> bool:
        selected[entry_index].add(sentence_index)
        if rendered_bytes() <= max_bytes:
            return True
        selected[entry_index].discard(sentence_index)
        blocked.add((entry_index, sentence_index))
        return False

    def fill_adjacent() -> None:
        """Spend leftover bytes on run boundaries after every scored move is exhausted."""

        while True:
            moves: list[tuple[int, int]] = []
            for entry_index, indices in selected.items():
                if not indices:
                    continue
                for run_start, run_end in _index_runs(sorted(indices)):
                    for neighbor in (run_start - 1, run_end + 1):
                        if (
                            0 <= neighbor < len(entries[entry_index].sentences)
                            and neighbor not in indices
                            and (entry_index, neighbor) not in blocked
                        ):
                            moves.append((entry_index, neighbor))
            if not moves:
                break
            entry_index, sentence_index = min(
                moves,
                key=lambda key: (-scores.get(key, 0.0), unit_bytes(key), priority_rank[key[0]], -key[1]),
            )
            apply(entry_index, sentence_index)

    def density(move: tuple[int, int, bool]) -> float:
        entry_index, sentence_index, opens_window = move
        value = scores.get((entry_index, sentence_index), 0.0)
        cost = unit_bytes((entry_index, sentence_index)) + _EVIDENCE_UNIT_BASE_COST
        if opens_window:
            cost += _EVIDENCE_WINDOW_OVERHEAD_BYTES
        return value / cost

    while True:
        moves: list[tuple[int, int, bool]] = []
        for entry_index, indices in selected.items():
            if not indices:
                continue
            for run_start, run_end in _index_runs(sorted(indices)):
                for neighbor in (run_start - 1, run_end + 1):
                    if (
                        0 <= neighbor < len(entries[entry_index].sentences)
                        and neighbor not in indices
                        and (entry_index, neighbor) not in blocked
                    ):
                        moves.append((entry_index, neighbor, False))
        for key, score in scores.items():
            if score > 0 and key[1] not in selected[key[0]] and key not in blocked:
                moves.append((key[0], key[1], True))
        if not moves:
            break
        entry_index, sentence_index, _ = max(
            moves,
            key=lambda move: (
                density(move),
                scores.get((move[0], move[1]), 0.0),
                -unit_bytes((move[0], move[1])),
                -priority_rank[move[0]],
                move[1],
            ),
        )
        apply(entry_index, sentence_index)
    if not any(selected.values()) and entries[0].sentences:
        apply(0, 0)
    fill_adjacent()
    return chosen()


def _render_evidence(chosen: Sequence[tuple[_EvidenceEntryData, int, int]]) -> str:
    """Render selected intervals in the standard prepared-context envelope."""

    items = [
        {
            "citation": {
                "scope_id": entry.scope_id,
                "memory_ref": entry.memory_ref.model_dump(mode="json"),
                "entry_id": entry.entry_id,
                "entry_version_id": entry.entry_version_id,
            },
            "content": entry.text[start:end],
            "start": start,
            "end": end,
        }
        for entry, start, end in chosen
    ]
    envelope = {"trust": "untrusted_history", "items": items}
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _interleave(
    memory: Sequence[_PreparedContextEntry],
    topics: Sequence[_PreparedContextEntry],
    experiences: Sequence[_PreparedContextEntry],
) -> tuple[_PreparedContextEntry, ...]:
    """Preserve each family's rank while alternating Memory, Topic, Experience."""

    ordered: list[_PreparedContextEntry] = []
    for index in range(max(len(memory), len(topics), len(experiences))):
        if index < len(memory):
            ordered.append(memory[index])
        if index < len(topics):
            ordered.append(topics[index])
        if index < len(experiences):
            ordered.append(experiences[index])
    return tuple(ordered)


def _interleave_groups(groups: Sequence[Sequence[_Item]]) -> tuple[_Item, ...]:
    ordered: list[_Item] = []
    for index in range(max((len(group) for group in groups), default=0)):
        ordered.extend(group[index] for group in groups if index < len(group))
    return tuple(ordered)


def _render(entries: Sequence[_PreparedContextEntry]) -> str:
    envelope = {
        "trust": "untrusted_history",
        "items": [_render_entry(entry) for entry in entries],
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _text_item(entry: _PreparedContextEntry) -> ContextTextItem:
    origin = entry.origin
    if isinstance(origin, MemoryEntryAddress):
        return ContextTextItem(
            artifact=origin.memory,
            content=entry.content,
            recall_rank=0,
            entry_id=origin.entry_id,
            entry_version_id=origin.entry_version_id,
        )
    if isinstance(origin, ArtifactAddress):
        return ContextTextItem(artifact=origin, content=entry.content, recall_rank=0)
    raise PreparedContextInvariantError("text-scope-missing")


def _render_entry(entry: _PreparedContextEntry) -> dict[str, object]:
    rendered: dict[str, object] = {
        "citation": entry.citation,
        "content": entry.content,
        "truncated": entry.truncated,
    }
    if entry.kind != "memory":
        rendered["kind"] = entry.kind
    return rendered


def _rendered_bytes(entries: Sequence[_PreparedContextEntry]) -> int:
    return len(_render(entries).encode("utf-8"))


def _truncate_utf8(text: str, byte_budget: int) -> str:
    prefix_budget = byte_budget - len(_ELLIPSIS.encode("utf-8"))
    encoded_prefix = text.encode("utf-8")[:prefix_budget]
    return f"{encoded_prefix.decode('utf-8', errors='ignore')}{_ELLIPSIS}"
