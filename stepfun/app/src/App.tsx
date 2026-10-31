import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Chunk, type SearchHit } from "./lib/api";
import { chunkDocument } from "./lib/chunker";
import { loadEvalSet } from "./lib/dataset";
import {
  hasWebGPU,
  loadEmbedder,
  gpuInfo,
  type BackendPref,
  type Embedder,
  type PrecisionOption,
} from "./lib/embedder";
import { runBenchmark, type BenchEvent, type BenchResult } from "./lib/bench";

function newKbId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function readKbId(): string {
  const stored = localStorage.getItem("stepfun.kbId");
  if (stored) return stored;
  const created = newKbId();
  localStorage.setItem("stepfun.kbId", created);
  return created;
}

const EXAMPLE_DOCS = 6;

export default function App() {
  const [kbId, setKbId] = useState(readKbId);
  const [count, setCount] = useState<number | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; target: string } | null>(null);
  const [serverError, setServerError] = useState("");

  const [precision, setPrecision] = useState<PrecisionOption>("auto");
  const [pref, setPref] = useState<BackendPref>("auto");
  const [gpu, setGpu] = useState<boolean | null>(null);
  const [deviceInfo, setDeviceInfo] = useState("");

  const [embedder, setEmbedder] = useState<Embedder | null>(null);
  const [loadingModel, setLoadingModel] = useState(false);
  const [loadNote, setLoadNote] = useState("");
  const embedderRef = useRef<{ key: string; handle: Embedder } | null>(null);

  const [filesBusy, setFilesBusy] = useState(false);
  const [importNote, setImportNote] = useState("");
  const [docIds, setDocIds] = useState<Set<string>>(new Set());
  const [embeddedCount, setEmbeddedCount] = useState(0);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searchNote, setSearchNote] = useState("");
  const [searching, setSearching] = useState(false);

  const [benchRunning, setBenchRunning] = useState(false);
  const [benchEvents, setBenchEvents] = useState<BenchEvent[]>([]);
  const [benchResults, setBenchResults] = useState<BenchResult[]>([]);
  const [benchEnv, setBenchEnv] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    hasWebGPU().then(async (supported) => {
      setGpu(supported);
      setDeviceInfo(await gpuInfo());
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const info = await api.health();
        if (cancelled) return;
        setHealth({ ok: info.ok, target: `${info.seekdb.host}:${info.seekdb.port}/${info.seekdb.database}` });
        const ensured = await api.ensure(kbId);
        if (!cancelled) setCount(ensured.count);
        setServerError("");
      } catch (error) {
        if (!cancelled) {
          setServerError(String((error as Error).message || error));
          setHealth(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kbId]);

  const ensureEmbedder = useCallback(async (): Promise<Embedder> => {
    const key = `${precision}:${pref}`;
    if (embedderRef.current?.key === key) return embedderRef.current.handle;
    if (embedderRef.current) {
      await embedderRef.current.handle.dispose().catch(() => undefined);
      embedderRef.current = null;
    }
    setLoadingModel(true);
    setLoadNote("加载模型…");
    try {
      const handle = await loadEmbedder(precision, pref, (event) => {
        if (event.status === "progress" && event.progress != null) {
          setLoadNote(`${event.file || "model"} ${event.progress.toFixed(0)}%`);
        } else if (event.status === "done" || event.status === "ready") {
          setLoadNote("初始化推理会话…");
        }
      });
      embedderRef.current = { key, handle };
      setEmbedder(handle);
      setLoadNote(`已就绪：${handle.backend.toUpperCase()} · ${handle.dtype} · 加载 ${handle.loadMs.toFixed(0)} ms`);
      return handle;
    } finally {
      setLoadingModel(false);
    }
  }, [precision, pref]);

  const importChunks = useCallback(
    async (chunks: Chunk[]) => {
      if (!chunks.length) return;
      if (!embedderRef.current) setImportNote("首次导入需要加载模型，请稍候…");
      const handle = await ensureEmbedder();
      setFilesBusy(true);
      try {
        const embedStart = performance.now();
        let embedded = 0;
        const vectors = await handle.embed(
          chunks.map((chunk) => chunk.text),
          (done, total) => {
            embedded = done;
            setImportNote(`本地向量化 ${done}/${total}`);
          },
        );
        const embedMs = performance.now() - embedStart;
        const result = await api.addDocuments(
          kbId,
          chunks.map((chunk) => ({
            id: chunk.id,
            text: chunk.text,
            metadata: { docId: chunk.docId, title: chunk.title, index: chunk.index },
          })),
          vectors,
        );
        const probeStart = performance.now();
        const probe = await api.search(kbId, chunks[0].text.slice(0, 120), vectors[0], 5);
        const probeMs = performance.now() - probeStart;
        const searchable = probe.results.some((hit) => hit.id === chunks[0].id);
        setImportNote(
          `已写入 ${result.upserted} 个分块（共 ${result.count}）· 向量化 ${embedMs.toFixed(0)} ms · 写入 ${result.upsertMs} ms · 索引刷新 ${result.refreshMs} ms · 刷新后检索${searchable ? "已命中" : "未命中"}（${probeMs.toFixed(0)} ms）`,
        );
        setDocIds((previous) => {
          const next = new Set(previous);
          chunks.forEach((chunk) => next.add(chunk.docId));
          return next;
        });
        setCount(result.count);
        setEmbeddedCount((value) => value + embedded);
      } finally {
        setFilesBusy(false);
      }
    },
    [ensureEmbedder, kbId],
  );

  const onFiles = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList?.length) return;
      const chunks: Chunk[] = [];
      const added: string[] = [];
      for (const file of Array.from(fileList)) {
        const text = await file.text();
        if (!text.trim()) continue;
        const docId = `file:${file.name}:${file.size}`;
        added.push(docId);
        chunks.push(...chunkDocument(docId, file.name, text));
      }
      if (!chunks.length) {
        setImportNote("没有可导入的文本内容");
        return;
      }
      await importChunks(chunks);
      setImportNote((note) => `${note} · 文件：${added.join("、")}`);
    },
    [importChunks],
  );

  const onPasteImport = useCallback(async () => {
    const area = document.getElementById("paste-area") as HTMLTextAreaElement | null;
    const content = area?.value?.trim();
    if (!content) {
      setImportNote("请先在文本框中粘贴内容");
      return;
    }
    const docId = `paste:${Date.now()}`;
    const title = content.split(/\n/)[0].slice(0, 60) || "粘贴文档";
    const chunks = chunkDocument(docId, title, content);
    await importChunks(chunks);
    if (area) area.value = "";
  }, [importChunks]);

  const loadExamples = useCallback(async () => {
    const evalSet = await loadEvalSet();
    const docs = evalSet.docs.slice(0, EXAMPLE_DOCS).filter((doc) => !docIds.has(doc.docId));
    if (!docs.length) {
      setImportNote("示例语料已全部导入");
      return;
    }
    const chunks = docs.flatMap((doc) => chunkDocument(doc.docId, doc.title, doc.text));
    await importChunks(chunks);
    setImportNote((note) => `${note} · 示例文档 ${docs.length} 篇`);
  }, [docIds, importChunks]);

  const onSearch = useCallback(async () => {
    if (!query.trim()) return;
    if (!count) {
      setSearchNote("知识库为空，请先导入语料");
      return;
    }
    setSearching(true);
    setSearchNote("计算查询向量…");
    try {
      const handle = await ensureEmbedder();
      const embedStart = performance.now();
      const [vector] = await handle.embed([query.trim()]);
      const embedMs = performance.now() - embedStart;
      setSearchNote("seekdb 混合检索中…");
      const start = performance.now();
      const result = await api.search(kbId, query.trim(), vector, 8);
      const totalMs = performance.now() - start;
      setHits(result.results);
      setSearchNote(
        `查询向量化 ${embedMs.toFixed(0)} ms · seekdb 混合检索 ${result.dbMs} ms · 端到端 ${(embedMs + totalMs).toFixed(0)} ms`,
      );
    } catch (error) {
      setSearchNote(`检索失败：${(error as Error).message}`);
    } finally {
      setSearching(false);
    }
  }, [count, ensureEmbedder, kbId, query]);

  const switchKb = useCallback(async () => {
    await embedderRef.current?.handle.dispose().catch(() => undefined);
    embedderRef.current = null;
    setEmbedder(null);
    setHits([]);
    setSearchNote("");
    setImportNote("");
    setDocIds(new Set());
    const created = newKbId();
    localStorage.setItem("stepfun.kbId", created);
    setKbId(created);
  }, []);

  const startBenchmark = useCallback(async () => {
    setBenchRunning(true);
    setBenchResults([]);
    setBenchEnv(null);
    setBenchEvents([{ phase: "start", message: "开始评测（24 条查询 / 42 篇摘要）" }]);
    try {
      const { results, environment } = await runBenchmark((event) => {
        setBenchEvents((previous) => [...previous.slice(-60), event]);
      });
      setBenchResults(results);
      setBenchEnv(environment);
    } finally {
      setBenchRunning(false);
    }
  }, []);

  const exportBenchmark = useCallback(() => {
    const payload = { environment: benchEnv, results: benchResults };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `stepfun-benchmark-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [benchEnv, benchResults]);

  const sizeLabel = embedder
    ? { fp32: "FP32 86.2 MB", int8: "INT8 21.8 MB" }[embedder.precision]
    : "加载后显示";
  const precisionLabel = precision === "auto" ? "自动" : precision.toUpperCase();
  const actualPrecision = embedder ? embedder.precision.toUpperCase() : precisionLabel;
  const actualBackend = embedder?.backend.toUpperCase();

  return (
    <div className="page">
      <header className="header">
        <div>
          <h1>端侧知识库 · seekdb 混合检索</h1>
          <p className="sub">
            all-MiniLM-L6-v2 在浏览器本地向量化，seekdb 内完成向量 + 全文混合检索
          </p>
        </div>
        <div className="badges">
          <span className={`badge ${actualBackend === "WEBGPU" ? "good" : actualBackend ? "warn" : ""}`}>
            推理后端：{actualBackend || (gpu === null ? "检测中" : gpu ? "WebGPU 可用" : "WASM")}
          </span>
          <span className="badge">精度：{actualPrecision}</span>
          <span className="badge">模型体积：{sizeLabel}</span>
          <span className={`badge ${health?.ok ? "good" : "bad"}`}>
            seekdb：{health ? health.target : "未连接"}
          </span>
        </div>
      </header>

      {embedder?.fallback && (
        <div className="callout warn">
          未检测到可用的 WebGPU（或 WebGPU 初始化失败），已自动降级至 WASM 推理（{embedder.precision.toUpperCase()}）；功能完整，延迟会高于 GPU 路径。
        </div>
      )}

      {serverError && (
        <div className="callout bad">
          无法连接后端：{serverError}。请先启动 seekdb 与 <code>server/</code>（见 README）。
        </div>
      )}

      <main className="grid">
        <section className="panel">
          <h2>知识库</h2>
          <div className="row">
            <span className="muted">集合：stepfun_kb_{kbId.toLowerCase()}</span>
            <span className="chip">分块数：{count ?? "-"}</span>
          </div>
          <div className="row">
            <label>
              精度
              <select value={precision} onChange={(event) => setPrecision(event.target.value as PrecisionOption)}>
                <option value="auto">自动（WebGPU→FP32 / WASM→INT8）</option>
                <option value="int8">INT8（动态量化）</option>
                <option value="fp32">FP32（基线）</option>
              </select>
            </label>
            <label>
              推理后端
              <select value={pref} onChange={(event) => setPref(event.target.value as BackendPref)}>
                <option value="auto">自动（优先 WebGPU）</option>
                <option value="webgpu">WebGPU</option>
                <option value="wasm">WASM</option>
              </select>
            </label>
          </div>
          {(loadingModel || loadNote) && <p className="note">{loadNote}</p>}

          <h2>导入语料</h2>
          <input
            type="file"
            multiple
            accept=".txt,.md,.markdown,.json,.csv,text/plain"
            disabled={filesBusy}
            onChange={(event) => onFiles(event.target.files)}
          />
          <textarea id="paste-area" placeholder="或粘贴一段文本，作为一篇文档导入…" rows={4} />
          <div className="row">
            <button onClick={onPasteImport} disabled={filesBusy}>
              导入粘贴文本
            </button>
            <button onClick={loadExamples} disabled={filesBusy}>
              导入示例语料（{EXAMPLE_DOCS} 篇）
            </button>
            <button className="ghost" onClick={switchKb}>
              新建知识库
            </button>
          </div>
          {filesBusy && <p className="note">处理中… 已向量化 {embeddedCount} 个分块</p>}
          {importNote && <p className="note">{importNote}</p>}
          <p className="hint">
            当前设备：{deviceInfo || "检测中"}；WebGPU {gpu === null ? "检测中" : gpu ? "可用" : "不可用，将自动使用 WASM"}。
          </p>
        </section>

        <section className="panel">
          <h2>检索</h2>
          <div className="searchbar">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSearch();
              }}
              placeholder="输入问题，例如：how do bacteria resist antibiotics?"
            />
            <button onClick={onSearch} disabled={searching}>
              {searching ? "检索中…" : "混合检索"}
            </button>
          </div>
          {searchNote && <p className="note">{searchNote}</p>}
          <ul className="hits">
            {hits.map((hit, index) => (
              <li key={`${hit.id}-${index}`}>
                <div className="hit-head">
                  <span className="rank">#{index + 1}</span>
                  <span className="hit-title">{String(hit.metadata?.title || hit.id)}</span>
                  <span className="hit-meta">
                    doc {String(hit.metadata?.docId || "?")} · {hit.distance == null ? "n/a" : hit.distance.toFixed(4)}
                  </span>
                </div>
                <p>{hit.text}</p>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <section className="panel bench">
        <div className="row space">
          <h2>端侧推理评测（FP32/INT8 × WebGPU/WASM）</h2>
          <div className="row">
            <button onClick={startBenchmark} disabled={benchRunning || !health?.ok}>
              {benchRunning ? "评测中…" : "运行评测"}
            </button>
            <button className="ghost" onClick={exportBenchmark} disabled={!benchResults.length}>
              导出 JSON
            </button>
          </div>
        </div>
        <p className="hint">
          评测集：SciFact 24 条 claim（每条唯一金标摘要）+ 24 篇干扰摘要，共 42 篇文档 / 24 条查询；指标为文档级
          Recall@5 与 nDCG@5。每次评测新建独立集合，写入后刷新索引并逐条检索。
        </p>
        {benchRunning && (
          <p className="note">
            {benchEvents.at(-1)?.config ? `[${benchEvents.at(-1)?.config}] ` : ""}
            {benchEvents.at(-1)?.message}
          </p>
        )}
        {benchResults.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>配置</th>
                  <th>模型体积</th>
                  <th>加载 / 预热 (ms)</th>
                  <th>向量化 (块/s)</th>
                  <th>写入+刷新 (ms)</th>
                  <th>查询向量化 (ms)</th>
                  <th>seekdb 检索 (ms)</th>
                  <th>端到端 P50 / P95 (ms)</th>
                  <th>Recall@5</th>
                  <th>nDCG@5</th>
                </tr>
              </thead>
              <tbody>
                {benchResults.map((result) => (
                  <tr key={result.label}>
                    <td>{result.label}</td>
                    <td>{(result.modelBytes / 1024 / 1024).toFixed(1)} MB</td>
                    <td>
                      {result.loadMs.toFixed(0)} / {result.warmupMs.toFixed(0)}
                    </td>
                    <td>{result.docsPerSecond.toFixed(1)}</td>
                    <td>
                      {result.upsertMs} + {result.refreshMs}
                    </td>
                    <td>{result.queryEmbedMedianMs}</td>
                    <td>{result.searchMedianMs}</td>
                    <td>
                      {result.e2eMedianMs} / {result.e2eP95Ms}
                    </td>
                    <td>{result.recallAt5.toFixed(3)}</td>
                    <td>{result.ndcgAt5.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {benchEnv && (
          <p className="hint">
            环境：{String(benchEnv.userAgent)}；GPU：{String(benchEnv.gpu)}；WebGPU 可用：{String(benchEnv.webgpu)}；
            查询 {String(benchEnv.queries)} 条 / 文档 {String(benchEnv.corpusDocs)} 篇 / 分块{" "}
            {String(benchEnv.chunkCount)} 个。
          </p>
        )}
      </section>

      <footer className="footer">
        <span>
          推理位置：浏览器（Transformers.js / ONNX Runtime Web）；存储与检索：seekdb（seekdb-js，DBMS_HYBRID_SEARCH）
        </span>
        <span>模型：Xenova/all-MiniLM-L6-v2 · 384 维 · 余弦距离</span>
      </footer>
    </div>
  );
}
