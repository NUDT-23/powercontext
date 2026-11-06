export type BackendKind = "webgpu" | "wasm";
export type Precision = "fp32" | "fp16" | "int8";

export interface BackendInfo {
  backend: BackendKind;
  precision: Precision;
  label: string;
  reason: string | null;
  gpuAdapter: string | null;
}

export interface GpuProbe {
  available: boolean;
  adapter: string | null;
  reason: string | null;
}

export function forcedWasm(): boolean {
  return new URLSearchParams(window.location.search).get("forceWasm") === "1";
}

interface NavigatorGpu {
  requestAdapter(options?: {
    powerPreference?: string;
  }): Promise<{
    info?: { vendor?: string; architecture?: string; description?: string };
  } | null>;
}

export async function probeWebGPU(): Promise<GpuProbe> {
  const gpu = (navigator as unknown as { gpu?: NavigatorGpu }).gpu;
  if (!gpu) {
    return { available: false, adapter: null, reason: "当前浏览器未暴露 WebGPU (navigator.gpu)" };
  }
  try {
    const adapter = await gpu.requestAdapter({
      powerPreference: "high-performance",
    });
    if (!adapter) {
      return { available: false, adapter: null, reason: "WebGPU 适配器不可用，已降级到 WASM" };
    }
    const info = (adapter as unknown as { info?: { vendor?: string; architecture?: string; description?: string } }).info;
    const name =
      info?.description ||
      [info?.vendor, info?.architecture].filter(Boolean).join(" ") ||
      "WebGPU adapter";
    return { available: true, adapter: name, reason: null };
  } catch (error) {
    return {
      available: false,
      adapter: null,
      reason: `WebGPU 探测失败：${errorMessage(error)}`,
    };
  }
}

export function backendLabel(backend: BackendKind, precision: Precision): string {
  return `${backend === "webgpu" ? "WebGPU" : "WASM"} · ${precision.toUpperCase()}`;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
