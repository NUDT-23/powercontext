import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpusDir = path.join(rootDir, "corpus");

const readLines = (file) =>
  fs
    .readFileSync(file, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

const docs = readLines(path.join(corpusDir, "docs.jsonl")).map((line, index) => {
  try {
    return JSON.parse(line);
  } catch (error) {
    throw new Error(`docs.jsonl 第 ${index + 1} 行不是合法 JSON: ${error.message}`);
  }
});
const queries = readLines(path.join(corpusDir, "eval", "queries.jsonl")).map(
  (line, index) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      throw new Error(`queries.jsonl 第 ${index + 1} 行不是合法 JSON: ${error.message}`);
    }
  }
);
const qrels = readLines(path.join(corpusDir, "eval", "qrels.tsv"))
  .filter((line) => !line.startsWith("#"))
  .map((line) => {
    const [queryId, docId, relevance] = line.split(/\t/);
    return { queryId, docId, relevance: Number(relevance) };
  });

const problems = [];
const docIds = new Set();
for (const doc of docs) {
  if (!doc.id || !doc.title || !doc.text) problems.push(`文档字段缺失: ${JSON.stringify(doc.id)}`);
  if (docIds.has(doc.id)) problems.push(`重复文档 ID: ${doc.id}`);
  docIds.add(doc.id);
  if (doc.text.length > 240) {
    problems.push(`文档 ${doc.id} 长度 ${doc.text.length} 超过 240，可能被切成多块`);
  }
}

const queryIds = new Set();
for (const query of queries) {
  if (!query.id || !query.query) problems.push(`查询字段缺失: ${JSON.stringify(query.id)}`);
  if (queryIds.has(query.id)) problems.push(`重复查询 ID: ${query.id}`);
  queryIds.add(query.id);
}

const relevantCount = new Map();
for (const qrel of qrels) {
  if (!queryIds.has(qrel.queryId)) problems.push(`qrels 引用未知查询: ${qrel.queryId}`);
  if (!docIds.has(qrel.docId)) problems.push(`qrels 引用未知文档: ${qrel.docId}`);
  if (![0, 1, 2].includes(qrel.relevance)) {
    problems.push(`qrels 相关性取值非法: ${qrel.queryId}/${qrel.docId}=${qrel.relevance}`);
  }
  if (qrel.relevance > 0) {
    relevantCount.set(qrel.queryId, (relevantCount.get(qrel.queryId) ?? 0) + 1);
  }
}
for (const queryId of queryIds) {
  if (!relevantCount.has(queryId)) problems.push(`查询 ${queryId} 没有正相关文档`);
}

if (problems.length > 0) {
  console.error("语料校验失败:");
  for (const problem of problems) console.error(` - ${problem}`);
  process.exit(1);
}

console.log(
  `语料校验通过: ${docs.length} 篇文档, ${queries.length} 条查询, ${qrels.length} 条 qrels, 平均每查询 ${(
    qrels.length / queries.length
  ).toFixed(2)} 条标注`
);
