"""抓取 arXiv 公开元数据，生成 seed/papers.json。

用法：
    python scripts/fetch_arxiv_seed.py
    python scripts/fetch_arxiv_seed.py --query 'all:"LLM agents"' --limit 12

仅保存标题、作者、年份、摘要与 arXiv ID，不含全文，用于竞赛演示。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"

DEFAULT_QUERIES = [
    'all:"LLM agents" AND all:memory',
    'all:"LLM agents" AND all:causal',
    'all:"agentic" AND all:planning',
]

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "seed" / "papers.json"
API = "https://export.arxiv.org/api/query"


def fetch(query: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    url = f"{API}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "PaperLens-seed/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        arxiv_id = (entry.findtext(f"{ATOM}id") or "").rsplit("/abs/", 1)[-1]
        arxiv_id = arxiv_id.split("v")[0] if arxiv_id else ""
        if not arxiv_id:
            continue
        published = entry.findtext(f"{ATOM}published") or ""
        authors = ", ".join(
            author.findtext(f"{ATOM}name") or "" for author in entry.findall(f"{ATOM}author")
        )
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": " ".join((entry.findtext(f"{ATOM}title") or "").split()),
                "authors": authors,
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "venue": "arXiv",
                "abstract": " ".join((entry.findtext(f"{ATOM}summary") or "").split()),
                "source": "arxiv",
                "primary_category": (entry.find(f"{ARXIV}primary_category") or {}).get(
                    "term", "cs.AI"
                )
                if entry.find(f"{ARXIV}primary_category") is not None
                else "cs.AI",
            }
        )
    return papers


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch arXiv metadata for seed corpus")
    parser.add_argument("--query", action="append", default=None, help="arXiv query (repeatable)")
    parser.add_argument("--limit", type=int, default=8, help="max results per query")
    parser.add_argument("--target", type=int, default=20, help="max unique papers to keep")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    queries = args.query or DEFAULT_QUERIES
    collected: dict[str, dict] = {}
    for query in queries:
        print(f"[fetch] {query}", file=sys.stderr)
        try:
            for paper in fetch(query, args.limit):
                collected.setdefault(paper["arxiv_id"], paper)
        except Exception as exc:  # noqa: BLE001 - keep other queries going
            print(f"[warn] query failed: {exc}", file=sys.stderr)
        time.sleep(3)  # arXiv API politeness
        if len(collected) >= args.target:
            break

    papers = list(collected.values())[: args.target]
    if not papers:
        print("No papers fetched; check network or query.", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[done] wrote {len(papers)} papers to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
