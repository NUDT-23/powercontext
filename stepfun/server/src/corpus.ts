import fs from "node:fs";
import path from "node:path";
import type { CorpusDoc, EvalQuery, Qrel } from "../../shared/types.js";

export interface CorpusBundle {
  docs: CorpusDoc[];
  queries: EvalQuery[];
  qrels: Qrel[];
}

function readLines(file: string): string[] {
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function loadCorpus(rootDir: string): CorpusBundle {
  const corpusDir = path.join(rootDir, "corpus");
  const docs = readLines(path.join(corpusDir, "docs.jsonl")).map(
    (line) => JSON.parse(line) as CorpusDoc
  );
  const queries = readLines(path.join(corpusDir, "eval", "queries.jsonl")).map(
    (line) => JSON.parse(line) as EvalQuery
  );
  const qrelsPath = path.join(corpusDir, "eval", "qrels.tsv");
  const qrels: Qrel[] = [];
  if (fs.existsSync(qrelsPath)) {
    for (const line of readLines(qrelsPath)) {
      if (line.startsWith("#")) continue;
      const [queryId, docId, relevance] = line.split(/\t|\s{2,}/);
      if (!queryId || !docId) continue;
      const rel = Number(relevance);
      if (rel !== 0 && rel !== 1 && rel !== 2) continue;
      qrels.push({ queryId, docId, relevance: rel });
    }
  }
  return { docs, queries, qrels };
}
