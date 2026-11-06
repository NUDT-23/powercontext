export function nowMs(): number {
  return Number(process.hrtime.bigint()) / 1e6;
}

export function elapsedMs(start: number): number {
  return Number(process.hrtime.bigint()) / 1e6 - start;
}

export function round(value: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}
