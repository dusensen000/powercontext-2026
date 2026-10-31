# 端侧知识库 · 阶跃星辰赛题（seekdb × 浏览器本地推理）

在浏览器中完成 embedding 推理，把向量、原文与元数据写入 seekdb，并通过 seekdb 的
`DBMS_HYBRID_SEARCH` 在数据库内完成“向量 + 全文”混合检索的迷你知识库。

- 推理位置：浏览器（Transformers.js 3.5.1 / ONNX Runtime Web），无任何云端推理调用
- 模型：`Xenova/all-MiniLM-L6-v2`（384 维，余弦距离），INT8 动态量化
- 存储与检索：seekdb 1.4.0（server 模式，seekdb-js 1.4.0）
- 前端：Vite 6 + React 18 + TypeScript；后端：Express（仅做 seekdb 读写代理，不做推理）

## 目录结构

```
stepfun/
├─ app/                      # 浏览器应用（Vite + React）
│  ├─ public/eval_set.json   # 评测集（SciFact 子集，24 queries / 42 docs）
│  ├─ public/models/         # 模型文件（不入库，见“模型获取”）
│  └─ src/
│     ├─ lib/embedder.ts     # 端侧推理、后端选择与 WebGPU→WASM 降级
│     ├─ lib/bench.ts        # 分阶段计时与检索质量评测
│     ├─ lib/chunker.ts      # 文档分块
│     ├─ lib/api.ts          # 调用本地后端
│     └─ App.tsx             # UI
├─ server/src/index.mjs      # seekdb API（集合管理、写入、刷新、混合检索）
├─ scripts/
│  ├─ fetch-models.sh        # 下载 FP32 ONNX 并生成 INT8 模型
│  ├─ quantize_onnx.py       # INT8 动态量化脚本
│  └─ start-seekdb.sh        # 启动本地 seekdb server
├─ docs/
│  ├─ TECHNICAL_NOTES.md     # 一页技术说明
│  ├─ model_quantization.json# 量化前后体积 / SHA-256 / 压缩比
│  └─ benchmark_results.json # 一次完整评测的原始结果（本机）
└─ README.md
```

## 环境要求

- Node.js ≥ 20（开发验证使用 v24）
- Chrome / Edge 最新版（Chromium 150 验证）；需支持 WebGPU 时优先 WebGPU，否则自动用 WASM
- seekdb 1.4.0 可执行文件（Linux / WSL2）。Windows 下建议在 WSL2 的 ext4 目录运行：
  seekdb 的全文索引依赖 `fallocate`，NTFS 路径（`/mnt/c`、`D:\`）上创建全文集合会挂起。
- 本机验证环境：Windows 11 + WSL2；seekdb 运行于 WSL2 发行版 `seekdb-fix1477`
  （`/srv/seekdb-fts-performance/build/seekdb`，数据目录 `/srv/stepfun-probe-db`，端口 2881）

## 快速开始

### 1. 获取模型并量化

```bash
cd stepfun
bash scripts/fetch-models.sh          # 需要 python3 + onnxruntime + onnx（Windows 可设 PYTHON=py）
```

脚本下载 `Xenova/all-MiniLM-L6-v2`（revision `751bff37182d3f1213fa05d7196b954e230abad9`）
的 FP32 ONNX 与 tokenizer 文件到 `app/public/models/minilm-fp32/`，并用
`scripts/quantize_onnx.py` 生成 `app/public/models/minilm-int8/onnx/model_quantized.onnx`。
依赖：`pip install onnxruntime onnx`。若网络受限可设置 `HF_BASE` 为其他镜像。

模型文件约 110 MB，已被 `.gitignore` 排除，不随源码提交。

### 2. 启动 seekdb

```bash
# Linux：
SEEKDB_BIN=/path/to/seekdb bash scripts/start-seekdb.sh

# 本机 Windows（WSL2，按实际发行版与路径修改）：
wsl.exe -d seekdb-fix1477 -e bash -lc 'bash /mnt/d/powercontext-2026/stepfun/scripts/start-seekdb.sh'

# 取得 WSL2 IP（本机 localhost 转发不可用）：
wsl.exe -d seekdb-fix1477 -e hostname -I
```

默认端口 2881，数据库 `test`，用户 `root`、空密码。

### 3. 启动后端（seekdb API 代理）

Windows 上 `app/node_modules`、`server/node_modules` 可先安装到有空间的磁盘再链接；
直接安装亦可（本机 D: 空间紧张，采用目录 junction 到 `C:`）：

```bash
cd stepfun/server
npm install --legacy-peer-deps --omit=optional
SEEKDB_HOST=<上一步的 WSL2 IP> SEEKDB_PORT=2881 npm start
# -> http://127.0.0.1:8787
```

`--omit=optional` 跳过 server 模式用不到的原生绑定；`--legacy-peer-deps` 规避
`@seekdb/default-embed` 的 workspace 协议依赖。

### 4. 启动前端

```bash
cd stepfun/app
npm install
npm run dev
# -> http://127.0.0.1:5173  （/api 已代理到 127.0.0.1:8787）
```

打开页面后：

1. 顶部徽标显示推理后端、解析后的精度、模型体积与 seekdb 连接状态；
2. “导入示例语料”或选择 `.txt/.md` 文件导入，观察本地向量化、写入与索引刷新耗时；
3. 输入问题执行“混合检索”，结果由 seekdb 混合检索返回，展示原文与分数；
4. 在“端侧推理评测”中点击“运行评测”，完成后可导出 JSON。

### 5. 验证 WebGPU → WASM 降级

正常打开时自动选择 WebGPU；若设备/浏览器不支持，自动降级 WASM 并在页面上显示黄色提示条。
可用测试开关强制走降级路径：

```
http://127.0.0.1:5173/?forcenogpu=1
```

此时精度自动解析为 INT8，后端徽标显示 `WASM`，页面提示“已自动降级至 WASM 推理”。

## 模型与量化

| 项目 | 值 |
| --- | --- |
| 模型 | `sentence-transformers/all-MiniLM-L6-v2` 的 ONNX 转换 `Xenova/all-MiniLM-L6-v2` |
| Revision | `751bff37182d3f1213fa05d7196b954e230abad9` |
| 许可 | Apache-2.0 |
| FP32 ONNX | 90,387,606 B，sha256 `759c3cd2…c469c46e` |
| INT8 ONNX | 22,869,072 B，sha256 `e13dcd11…80d6021a` |
| 量化方式 | `onnxruntime.quantization.quantize_dynamic(QInt8, MatMulConstBOnly=True)` |
| 压缩比 | 3.952×（体积减少 74.7%） |

完整报告见 [docs/model_quantization.json](docs/model_quantization.json)。

## 评测与复现

- 评测集：`app/public/eval_set.json`，取自 SciFact dev split（Wadden et al. 2020，CC BY 4.0）：
  24 条 claim（每条恰有一个金标摘要）+ 24 篇同领域干扰摘要，共 42 篇文档；文档级标注。
- 分块：按句子切分，目标 600 字符、上限 900 字符，共 120 个分块。
- 指标：Recall@5、nDCG@5（按 `docId` 去重后计算，避免同一文档多分块抬高分数）。
- 计时：模型加载、预热、文档向量化、写入、索引刷新、查询向量化、seekdb 检索、端到端；
  每阶段取 24 次查询的中位数，端到端同时报告 P50/P95。首次加载与预热后分开记录。
- 固定条件：同一设备 / 浏览器 / 语料 / 查询集；每组配置新建独立集合并刷新索引。
- 结果：见 [docs/TECHNICAL_NOTES.md](docs/TECHNICAL_NOTES.md) 与
  [docs/benchmark_results.json](docs/benchmark_results.json)。

复现实验时请保持同一机器、浏览器版本与 seekdb 配置；对比单项优化时只改变一个变量。

## 实现要点

- **端侧推理**：`pipeline("feature-extraction", dir, { device, dtype })`，`fp32 → model.onnx`，
  `q8 → model_quantized.onnx`；模型从 `public/models` 本地加载（`allowRemoteModels=false`），
  推理全部发生在浏览器。WebGPU 不可用或初始化失败时自动重试 WASM。
- **后端感知的精度策略**：`自动` 模式在 WebGPU 下使用 FP32 权重，在 WASM 下使用 INT8。
  原因是 ONNX Runtime WebGPU 对 INT8 算子支持有限，q8 在 GPU 上会回退导致明显变慢；
  实测见技术说明。用户也可显式选择 INT8 / FP32。
- **seekdb 数据层**：每个知识库一个集合（`stepfun_kb_<kbId>`），schema 同时建立
  HNSW（384 维，cosine）与 ngram 全文索引（`ngram_token_size=3`）；写入分批 upsert，
  完成后调用 `refresh_index()`（`CALL dbms_index_manager.refresh()`）。
- **数据库内混合检索**：`collection.hybridSearch({ query: { whereDocument: { $contains } },
  knn: { queryEmbeddings } })` 由 seekdb 的 `DBMS_HYBRID_SEARCH` 在单条 SQL 内融合，
  客户端不会分别取两路结果再拼合。
- **状态管理**：知识库 ID 持久化到 `localStorage`，切换知识库会重建集合会话、清空结果；
  增量导入先 upsert 再刷新，刷新后用首块做一次探针检索确认可检索。

## 已知限制

- INT8 + WebGPU 在本机 iGPU（Intel gen-11）上明显慢于 FP32 + WebGPU：ONNX Runtime WebGPU
  缺少原生 int8 算子，量化权重需回退/反量化（查询向量化约慢 6 倍）。因此默认“自动”在 GPU 上选 FP32。
  INT8 的优势体现在 WASM 路径（查询延迟约减半、体积 1/4）。
- seekdb 嵌入式模式在 NTFS 上创建全文索引会挂起，本项目在 Windows 下使用 WSL2 中的
  seekdb server；嵌入式向量检索在 NTFS 下可用，但不满足全文混合检索要求。
- 评测集较小（24 条查询），指标主要用于同一设备上的相对比较，不代表大规模基准。
