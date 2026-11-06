export const EMBEDDING_DIMENSION = 512;

export function decodeEmbedding(base64: string, label = "embedding"): number[] {
  if (typeof base64 !== "string" || base64.length === 0) {
    throw new Error(`${label}: expected base64 float32 payload`);
  }
  const buf = Buffer.from(base64, "base64");
  if (buf.byteLength !== EMBEDDING_DIMENSION * 4) {
    throw new Error(
      `${label}: expected ${EMBEDDING_DIMENSION} float32 values (${EMBEDDING_DIMENSION * 4} bytes), got ${buf.byteLength} bytes`
    );
  }
  const view = new Float32Array(
    buf.buffer,
    buf.byteOffset,
    EMBEDDING_DIMENSION
  );
  const out = Array.from(view);
  for (let i = 0; i < out.length; i += 1) {
    if (!Number.isFinite(out[i])) {
      throw new Error(`${label}: non-finite value at index ${i}`);
    }
  }
  return out;
}

export function encodeEmbedding(values: readonly number[]): string {
  if (values.length !== EMBEDDING_DIMENSION) {
    throw new Error(
      `encodeEmbedding: expected ${EMBEDDING_DIMENSION} values, got ${values.length}`
    );
  }
  const view = new Float32Array(values);
  return Buffer.from(view.buffer, view.byteOffset, view.byteLength).toString(
    "base64"
  );
}

export function decodeEmbeddingList(
  base64List: unknown,
  label = "embeddings"
): number[][] {
  if (!Array.isArray(base64List) || base64List.length === 0) {
    throw new Error(`${label}: expected a non-empty array`);
  }
  return base64List.map((value, index) =>
    decodeEmbedding(String(value), `${label}[${index}]`)
  );
}
