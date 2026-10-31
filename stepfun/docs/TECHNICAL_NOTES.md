# 一页技术说明：端侧 AI 推理性能优化与 seekdb 混合检索

## 1. 模型与量化

| 项 | 内容 |
| --- | --- |
| 模型 | `Xenova/all-MiniLM-L6-v2`（`sentence-transformers/all-MiniLM-L6-v2` 的 ONNX 转换），Apache-2.0 |
| Revision | `751bff37182d3f1213fa05d7196b954e230abad9` |
| 结构 | 6 层 BERT，隐藏维 384，最大长度 512，池化方式 mean + L2 normalize |
| 量化 | `onnxruntime.quantization.quantize_dynamic`，QInt8；`MatMulConstBOnly=True`，per-channel=false，无校准数据 |
| FP32 体积 | 90,387,606 B（86.2 MiB），sha256 `759c3cd2…c469c46e` |
| INT8 体积 | 22,869,072 B（21.8 MiB），sha256 `e13dcd11…80d6021a` |
| 压缩比 | **3.952×**（减少 74.7%） |

量化脚本：`scripts/quantize_onnx.py`；原始模型下载：`scripts/fetch-models.sh`（HF 镜像，固定 revision）；
完整报告：`docs/model_quantization.json`。量化只作用于推理权重，tokenizer 与池化逻辑不变。

**检索质量**（SciFact dev 子集：24 条 claim / 42 篇摘要 / 120 个分块；文档级 Recall@5、nDCG@5，
按 docId 去重；混合检索由 seekdb 返回顺序计算）：

| 配置 | Recall@5 | nDCG@5 |
| --- | --- | --- |
| FP32 + WASM（基线） | 1.000 | 1.000 |
| INT8 + WASM | 1.000 | 1.000 |
| FP32 + WebGPU | 1.000 | 1.000 |
| INT8 + WebGPU | 1.000 | 0.970 |

两次独立运行结果一致：INT8 在 WASM/WebGPU 上的 Recall@5 均无变化；INT8+WebGPU 的 nDCG@5 由
1.000 降至 0.970（同一文档内分块顺序互换，文档命中未变）。评测集仅 24 条查询，指标用于同机相对比较。

## 2. 端侧运行与降级

- 运行时：Transformers.js 3.5.1 + ONNX Runtime Web（`wasm`/`webgpu` EP）。模型从
  `app/public/models` 本地加载（`allowRemoteModels=false`），文档与查询向量均在浏览器内计算，
  无云端推理调用。
- 后端选择：启动时 `navigator.gpu.requestAdapter()` 探测；`pipeline(..., { device: "webgpu" | "wasm",
  dtype })` 显式指定。`fp32 → model.onnx`，INT8 → `model_quantized.onnx`（`dtype: "q8"`）。
- 自动降级：无 adapter 或 WebGPU 会话初始化失败时重试 WASM，并在页面顶部显示黄色提示条
  （“已自动降级至 WASM 推理（INT8）”），徽标同步显示实际后端。测试开关
  `?forcenogpu=1` 可复现降级路径（已验证：自动解析为 WASM + INT8，检索正常）。
- 精度策略（后端感知）：`自动` 在 WebGPU 下用 FP32、WASM 下用 INT8。依据见 §4：
  INT8 权重在 WASM 上更快更小，而本机 ORT WebGPU 缺少原生 int8 算子，q8 反而变慢。
  用户可显式选择 INT8 或 FP32 进行复现。

## 3. seekdb 存储与混合检索

- 部署：seekdb 1.4.0 server 模式（WSL2，ext4），seekdb-js 1.4.0 通过 MySQL 协议连接；
  每个知识库一个集合 `stepfun_kb_<kbId>`。
- Schema：`VectorIndexConfig({ hnsw: { dimension: 384, distance: "cosine" } })` +
  `FulltextIndexConfig("ngram", { ngram_token_size: 3 })`；文档存原文与
  `{ docId, title, index }` 元数据，`id = <docId>::<chunkIndex>`。
- 写入：前端按 8 条一批做 embedding，后端按 32 条一批 `upsert`；导入完成后调用
  `collection.refresh_index()`（`CALL dbms_index_manager.refresh()`），再用首块做一次探针检索，
  确认刷新后新内容可被检索（评测中 `searchableAfterRefresh=true`）。
- 混合检索：`collection.hybridSearch({ query: { whereDocument: { $contains: q } },
  knn: { queryEmbeddings: [v] }, nResults, include })`，由 seekdb 的
  `DBMS_HYBRID_SEARCH.GET_SQL` 在数据库内以单条 SQL 融合向量与全文结果；客户端不分别取两路再拼合。
  检索阶段 seekdb 耗时中位数 16–24 ms（120 分块）。
- 状态管理：`kbId` 持久化在 `localStorage`；“新建知识库”会释放推理会话、清空结果与分块计数并
  切换到新集合；增量导入只 upsert 新分块并刷新索引，连续导入/切换后检索结果与当前集合一致。

## 4. 优化与实测结果

优化点：本地模型加载（不走网络）、文档批处理（embedding batch=8、upsert batch=32）、
入库后一次性刷新索引、WebGPU 推理 + 后端感知精度、查询前预热。

测试条件：Windows 11，8 线程；Intel gen-11 iGPU；Chromium 150（Qoder 内置浏览器）；
seekdb 1.4.0 server（WSL2）；语料 42 篇 / 120 分块；24 条查询；同机同浏览器同查询集；
每组配置独立集合、写入后刷新；计时为 24 次查询中位数，端到端含查询向量化 + HTTP + seekdb。

| 配置 | 模型体积 | 加载 / 预热 (ms) | 向量化 (块/s) | 写入 + 刷新 (ms) | 查询向量化 (ms) | seekdb 检索 (ms) | 端到端 P50 / P95 (ms) | Recall@5 | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FP32 + WASM（基线） | 86.2 MiB | 3972 / 310 | 0.86 | 1865.7 + 534.2 | 133.05 | 23.85 | 179.65 / 357.8 | 1.000 | 1.000 |
| INT8 + WASM | 21.8 MiB | 1466 / 50 | 1.76 | 1603.7 + 817.3 | 96.75 | 18.6 | 123.8 / 230.2 | 1.000 | 1.000 |
| FP32 + WebGPU | 86.2 MiB | 2615 / 185 | **15.27** | 1893.1 + 704 | 42.25 | 16.3 | **71.3 / 87.4** | 1.000 | 1.000 |
| INT8 + WebGPU | 21.8 MiB | 1212 / 273 | 1.45 | 1903.2 + 725.3 | 261.75 | 17.4 | 293.35 / 394.1 | 1.000 | 0.970 |

重复运行（同日第一次，条件同上）：FP32+WASM 141.8/251.7 ms、INT8+WASM 95.85/127 ms、
FP32+WebGPU 68.75/88.1 ms、INT8+WebGPU 362.2/620 ms（端到端 P50/P95），
各配置 Recall@5 均为 1.000，INT8+WebGPU nDCG@5 同样为 0.970。两次运行取中位数：
**160.7 / 109.8 / 70.0 / 327.8 ms**（按表中行序）。原始数据：
`docs/benchmark_results.json`、`docs/benchmark_results_run1.json`。

结论：

- 相对 FP32+WASM 基线，**FP32+WebGPU** 把文档向量化吞吐从 0.9 提升到 15.3 块/s（本次运行约 17×；
  首次运行 1.5→11.3 块/s，约 8×），端到端查询延迟从约 180 ms 降到约 71 ms（约 2.5×），检索质量不变。
- **INT8+WASM** 将模型体积降至 1/3.95，查询向量化约减半（133→97 ms），端到端降低约 31%，
  是 WebGPU 不可用时的最优回退组合。
- **INT8+WebGPU 不推荐**：本机 ORT WebGPU 对量化算子回退，查询向量化 262–337 ms，
  端到端 293–362 ms，虽仍可用但明显慢于 FP32+WebGPU。这也是 `自动` 模式在 GPU 上选 FP32 的原因。
- 首次加载与预热分开报告；所有延迟为预热后的中位数（P50），另给 P95；未只取最快一次。
- 局限：评测集较小，设备为集成 GPU；不同 GPU/驱动下 INT8 的 GPU 表现可能不同，结论以本机实测为准。
