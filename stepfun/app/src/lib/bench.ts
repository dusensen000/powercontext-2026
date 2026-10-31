import { api, type Chunk } from "./api";
import { chunkAll } from "./chunker";
import { loadEvalSet } from "./dataset";
import { loadEmbedder, hasWebGPU, gpuInfo, type Backend, type BackendPref, type Precision } from "./embedder";
import { mean, median, ndcgAtK, percentile, recallAtK } from "./metrics";

export interface BenchConfig {
  label: string;
  precision: Precision;
  pref: BackendPref;
}

export interface BenchResult {
  label: string;
  precision: Precision;
  requestedBackend: BackendPref;
  backend: Backend;
  dtype: string;
  modelBytes: number;
  loadMs: number;
  warmupMs: number;
  chunks: number;
  embedMs: number;
  docsPerSecond: number;
  upsertMs: number;
  refreshMs: number;
  queryEmbedMedianMs: number;
  searchMedianMs: number;
  e2eMedianMs: number;
  e2eP95Ms: number;
  recallAt5: number;
  ndcgAt5: number;
  failures: number;
  searchableAfterRefresh: boolean;
}

export interface BenchEvent {
  phase: "start" | "loading" | "indexing" | "querying" | "done" | "error";
  config?: string;
  message: string;
  done?: number;
  total?: number;
}

const MODEL_FILES: Record<Precision, string> = {
  fp32: "/models/minilm-fp32/onnx/model.onnx",
  int8: "/models/minilm-int8/onnx/model_quantized.onnx",
};

async function fileSize(url: string): Promise<number> {
  try {
    const response = await fetch(url, { method: "HEAD" });
    return Number(response.headers.get("content-length") || 0);
  } catch {
    return 0;
  }
}

export async function runBenchmark(
  onEvent: (event: BenchEvent) => void,
): Promise<{ results: BenchResult[]; environment: Record<string, unknown> }> {
  const evalSet = await loadEvalSet();
  const chunks = chunkAll(evalSet.docs);
  const gpu = await hasWebGPU();
  const configs: BenchConfig[] = [
    { label: "FP32 + WASM", precision: "fp32", pref: "wasm" },
    { label: "INT8 + WASM", precision: "int8", pref: "wasm" },
  ];
  if (gpu) {
    configs.push(
      { label: "FP32 + WebGPU", precision: "fp32", pref: "webgpu" },
      { label: "INT8 + WebGPU", precision: "int8", pref: "webgpu" },
    );
  }
  const sizes = {
    fp32: await fileSize(MODEL_FILES.fp32),
    int8: await fileSize(MODEL_FILES.int8),
  };
  const results: BenchResult[] = [];

  for (const config of configs) {
    onEvent({ phase: "loading", config: config.label, message: "加载模型" });
    try {
      const embedder = await loadEmbedder(config.precision, config.pref, (event) => {
        if (event.status === "progress" && event.progress != null) {
          onEvent({
            phase: "loading",
            config: config.label,
            message: `${event.file || "model"} ${event.progress.toFixed(0)}%`,
            done: event.progress,
            total: 100,
          });
        }
      });
      const kbId = `bench_${config.precision}_${embedder.backend}_${Date.now()}`;
      onEvent({
        phase: "indexing",
        config: config.label,
        message: `索引 ${chunks.length} 个分块 (${embedder.backend})`,
      });
      const embedStart = performance.now();
      const vectors = await embedder.embed(
        chunks.map((chunk) => chunk.text),
        (done, total) => onEvent({ phase: "indexing", config: config.label, message: `向量化 ${done}/${total}`, done, total }),
      );
      const embedMs = performance.now() - embedStart;
      const { upsertMs, refreshMs } = await api.addDocuments(
        kbId,
        chunks.map(toDocument),
        vectors,
      );

      onEvent({ phase: "querying", config: config.label, message: "执行 24 条查询" });
      const recalls: number[] = [];
      const ndcgs: number[] = [];
      const embedLatencies: number[] = [];
      const searchLatencies: number[] = [];
      const e2eLatencies: number[] = [];
      let failures = 0;
      let searchableAfterRefresh = true;
      for (const [index, item] of evalSet.queries.entries()) {
        const queryStart = performance.now();
        const [queryVector] = await embedder.embed([item.query]);
        const embedMsQuery = performance.now() - queryStart;
        let hits;
        try {
          hits = await api.search(kbId, item.query, queryVector, 5);
        } catch (error) {
          failures += 1;
          if (index === 0) searchableAfterRefresh = false;
          console.warn("search failed", error);
          continue;
        }
        const total = performance.now() - queryStart;
        embedLatencies.push(embedMsQuery);
        searchLatencies.push(hits.dbMs);
        e2eLatencies.push(total);
        const docIds = hits.results.map((hit) => String(hit.metadata?.docId || hit.id.split("::")[0]));
        recalls.push(recallAtK(docIds, item.goldDocId, 5));
        ndcgs.push(ndcgAtK(docIds, item.goldDocId, 5));
        if (index === 0 && hits.results.length === 0) searchableAfterRefresh = false;
        onEvent({
          phase: "querying",
          config: config.label,
          message: `查询 ${index + 1}/${evalSet.queries.length}`,
          done: index + 1,
          total: evalSet.queries.length,
        });
      }
      results.push({
        label: `${config.label}${embedder.backend !== config.pref ? ` (实际 ${embedder.backend})` : ""}${
          embedder.precision !== config.precision ? ` · ${embedder.precision.toUpperCase()}` : ""
        }`,
        precision: embedder.precision,
        requestedBackend: config.pref,
        backend: embedder.backend,
        dtype: embedder.dtype,
        modelBytes: sizes[embedder.precision],
        loadMs: round(embedder.loadMs),
        warmupMs: round(embedder.warmupMs),
        chunks: chunks.length,
        embedMs: round(embedMs),
        docsPerSecond: round((chunks.length / embedMs) * 1000),
        upsertMs,
        refreshMs,
        queryEmbedMedianMs: round(median(embedLatencies)),
        searchMedianMs: round(median(searchLatencies)),
        e2eMedianMs: round(median(e2eLatencies)),
        e2eP95Ms: round(percentile(e2eLatencies, 95)),
        recallAt5: round(mean(recalls)),
        ndcgAt5: round(mean(ndcgs)),
        failures,
        searchableAfterRefresh,
      });
      await embedder.dispose();
      await api.removeKb(kbId).catch(() => undefined);
    } catch (error) {
      onEvent({ phase: "error", config: config.label, message: String((error as Error)?.message || error) });
    }
  }

  onEvent({ phase: "done", message: "评测完成" });
  return {
    results,
    environment: {
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
      webgpu: gpu,
      gpu: await gpuInfo(),
      queries: evalSet.queries.length,
      corpusDocs: evalSet.docs.length,
      chunkCount: chunks.length,
      timestamp: new Date().toISOString(),
      seekdb: "seekdb 1.4.0 server mode via seekdb-js",
    },
  };
}

function toDocument(chunk: Chunk) {
  return {
    id: chunk.id,
    text: chunk.text,
    metadata: { docId: chunk.docId, title: chunk.title, index: chunk.index },
  };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
