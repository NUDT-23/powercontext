from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from .models import SourceDoc

REQ_RE = re.compile(r"\b([RC]\d+)\b", re.IGNORECASE)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _component(rel: str, text: str) -> str:
    blob = f"{rel} {text}".lower()
    if "search" in blob or "搜索" in blob or "检索" in blob:
        return "search"
    if "auth" in blob or "登录" in blob or "认证" in blob:
        return "auth"
    return "general"


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _markdown_docs(path: Path, rel: str, text: str) -> list[SourceDoc]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    sections: list[tuple[int, int, str]] = []
    if not matches:
        title = re.search(r"(?m)^#\s+(.+?)\s*$", text)
        sections.append((0, len(text), title.group(1).strip() if title else path.stem))
    else:
        if matches[0].start() > 0:
            sections.append((0, matches[0].start(), "preamble"))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections.append((start, end, match.group(1).strip()))

    docs: list[SourceDoc] = []
    for start, end, heading in sections:
        body = text[start:end].strip()
        if not body:
            continue
        req_ids = sorted({item.upper() for item in REQ_RE.findall(body)})
        if req_ids:
            key = req_ids[0]
        else:
            slug = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", heading).strip("-")[:40]
            key = slug or "section"
        docs.append(
            SourceDoc(
                id=f"spec:{rel}:{key}",
                kind="spec",
                path=rel,
                symbol=heading,
                heading=heading,
                content=body,
                line_start=_line_at(text, start),
                line_end=_line_at(text, end),
                content_hash=_hash(body),
                metadata={"component": _component(rel, body), "requirement_ids": ",".join(req_ids)},
            )
        )
    return docs


def _python_docs(path: Path, rel: str, text: str, kind: str) -> list[SourceDoc]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    docs: list[SourceDoc] = []
    module_doc = ast.get_docstring(tree)
    if module_doc:
        docs.append(
            SourceDoc(
                id=f"{kind}:{rel}:<module>",
                kind=kind,
                path=rel,
                symbol="<module>",
                heading=f"{rel}:module",
                content=module_doc,
                line_start=1,
                line_end=max(1, len(text.splitlines())),
                content_hash=_hash(module_doc),
                metadata={"component": _component(rel, module_doc)},
            )
        )

    for node in tree.body:
        if kind == "test":
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        segment = ast.get_source_segment(text, node)
        if not segment:
            continue
        req_ids = sorted({item.upper() for item in REQ_RE.findall(f"{ast.get_docstring(node) or ''}\n{segment}")})
        meta: dict[str, str] = {"component": _component(rel, segment)}
        if kind == "test":
            meta["test_kind"] = "target" if "target" in rel.lower() else "regression"
            meta["covers"] = ",".join(req_ids)
        else:
            meta["requirement_ids"] = ",".join(req_ids)
        docs.append(
            SourceDoc(
                id=f"{kind}:{rel}:{node.name}",
                kind=kind,
                path=rel,
                symbol=node.name,
                heading=f"{rel}:{node.name}",
                content=segment,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", None) or node.lineno,
                content_hash=_hash(segment),
                metadata=meta,
            )
        )
    return docs


def iter_project_docs(project_dir: Path) -> list[SourceDoc]:
    docs: list[SourceDoc] = []
    specs_dir = project_dir / "specs"
    if specs_dir.exists():
        for path in sorted(specs_dir.rglob("*.md")):
            rel = path.relative_to(project_dir).as_posix()
            docs.extend(_markdown_docs(path, rel, path.read_text(encoding="utf-8")))
    for path in sorted(project_dir.rglob("*.py")):
        rel = path.relative_to(project_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel.startswith("tests/") or "/tests/" in f"/{rel}":
            docs.extend(_python_docs(path, rel, text, "test"))
        else:
            docs.extend(_python_docs(path, rel, text, "code"))
    return docs
