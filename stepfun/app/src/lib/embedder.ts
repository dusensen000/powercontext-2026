import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

export type Precision = "fp32" | "int8";
export type PrecisionOption = Precision | "auto";
export type BackendPref = "auto" | "webgpu" | "wasm";
export type Backend = "webgpu" | "wasm";

export interface LoadProgress {
  status: string;
  file?: string;
  progress?: number;
  loaded?: number;
  total?: number;
}

export interface Embedder {
  precision: Precision;
  backend: Backend;
  requestedBackend: BackendPref;
  fallback: boolean;
  dtype: string;
  loadMs: number;
  warmupMs: number;
  embed(texts: string[], onBatch?: (done: number, total: number) => void): Promise<number[][]>;
  dispose(): Promise<void>;
}

const MODEL_DIRS: Record<Precision, string> = {
  fp32: "minilm-fp32",
  int8: "minilm-int8",
};

const DTYPES = {
  fp32: "fp32",
  int8: "q8",
} as const satisfies Record<Precision, string>;

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = "/models/";
env.useBrowserCache = false;
(env.backends.onnx as { wasm: { numThreads: number } }).wasm.numThreads = 1;

let webgpuSupport: Promise<boolean> | null = null;

export function hasWebGPU(): Promise<boolean> {
  if (!webgpuSupport) {
    webgpuSupport = (async () => {
      if (new URLSearchParams(window.location.search).has("forcenogpu")) return false;
      const gpu = (navigator as unknown as { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
      if (!gpu) return false;
      try {
        return Boolean(await gpu.requestAdapter());
      } catch {
        return false;
      }
    })();
  }
  return webgpuSupport;
}

export async function gpuInfo(): Promise<string> {
  if (new URLSearchParams(window.location.search).has("forcenogpu")) return "simulated none";
  const gpu = (navigator as unknown as {
    gpu?: { requestAdapter(): Promise<{ info?: Record<string, string> } | null> };
  }).gpu;
  if (!gpu) return "none";
  try {
    const adapter = await gpu.requestAdapter();
    const info = adapter?.info;
    if (!info) return "available";
    return [info.vendor, info.architecture, info.device, info.description]
      .filter(Boolean)
      .join(" / ");
  } catch {
    return "unavailable";
  }
}

async function createExtractor(
  precision: Precision,
  backend: Backend,
  onLoadProgress?: (event: LoadProgress) => void,
): Promise<FeatureExtractionPipeline> {
  const created = await pipeline("feature-extraction", MODEL_DIRS[precision], {
    device: backend,
    dtype: DTYPES[precision],
    progress_callback: (event: unknown) => {
      const payload = event as LoadProgress;
      onLoadProgress?.({
        status: payload.status,
        file: payload.file,
        progress: payload.progress,
        loaded: payload.loaded,
        total: payload.total,
      });
    },
  });
  return created as unknown as FeatureExtractionPipeline;
}

export async function loadEmbedder(
  requested: PrecisionOption,
  pref: BackendPref = "auto",
  onLoadProgress?: (event: LoadProgress) => void,
): Promise<Embedder> {
  const gpu = pref === "wasm" ? false : pref === "webgpu" ? true : await hasWebGPU();
  let backend: Backend = pref === "wasm" ? "wasm" : gpu ? "webgpu" : "wasm";
  let precision: Precision = requested === "auto" ? (backend === "webgpu" ? "fp32" : "int8") : requested;
  let extractor: FeatureExtractionPipeline | null = null;
  let fallback = pref !== "wasm" && backend === "wasm";
  const warm = async (): Promise<number> => {
    const startedWarm = performance.now();
    await extractor!(["warmup query"], { pooling: "mean", normalize: true });
    return performance.now() - startedWarm;
  };
  let loadMs = 0;
  let warmupMs = 0;
  const started = performance.now();
  try {
    extractor = await createExtractor(precision, backend, onLoadProgress);
    loadMs = performance.now() - started;
    warmupMs = await warm();
  } catch (error) {
    if (backend !== "webgpu") throw error;
    console.warn("WebGPU inference failed, falling back to WASM", error);
    backend = "wasm";
    fallback = true;
    if (requested === "auto") precision = "int8";
    const retryStart = performance.now();
    extractor = await createExtractor(precision, backend, onLoadProgress);
    loadMs = performance.now() - retryStart;
    warmupMs = await warm();
  }

  const runBatch = async (batch: string[]): Promise<number[][]> => {
    const output = await extractor!(batch, { pooling: "mean", normalize: true });
    return output.tolist() as number[][];
  };

  return {
    precision,
    backend,
    requestedBackend: pref,
    fallback,
    dtype: DTYPES[precision],
    loadMs,
    warmupMs,
    async embed(texts, onBatch) {
      const vectors: number[][] = [];
      const batchSize = 8;
      for (let offset = 0; offset < texts.length; offset += batchSize) {
        const batch = texts.slice(offset, offset + batchSize);
        vectors.push(...(await runBatch(batch)));
        onBatch?.(Math.min(offset + batch.length, texts.length), texts.length);
      }
      return vectors;
    },
    async dispose() {
      await extractor?.dispose();
      extractor = null;
    },
  };
}
