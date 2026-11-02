# 记忆酒馆：会记仇的老巴（Dify × seekdb × PowerContext）

一个可以真的“记仇”的 Dify 互动小游戏。你在酒馆里赊账、吹牛、撒谎、顺走杯子；老板老巴会把每一笔都记下来。换个会话、重启服务，只要你还用同一个玩家 ID 进门，他会把上次的账和你的原话翻出来。

- Dify Chatflow 负责对话入口、模型调用、两次工具调用与结果输出。
- **seekdb** 存酒馆素材（传闻/酒单/店规/常客）和每个玩家的账本、回合日志。
- **PowerContext** 存跨会话的情节记忆：你说过什么、老巴当时怎么回、最后怎么判定。

## 1. 怎么玩

1. 打开 Dify 应用，填一个玩家 ID（如 `alice`），进入酒馆。
2. 第一晚：
   - `老巴，来杯火焰威士忌，先记我账上，明天还你。`
   - `我昨天说的是下周还，你可别记错了。`
3. 结束会话（可以顺手重启后端），**新建一个 Dify 会话**，仍然填 `alice`：
   - `老巴，我又来了，今天有什么好酒？`
   - 老巴会先提你欠的 8 币和上次改口的事。
4. 想翻篇：
   - `对不起，上次是我不对。我这就还你 8 币。`
   - 账本归零，仇怨归零；账本末尾会显示结算结果。

店里的隐藏内容：地下室有龙、老巴的假眼、镇长欠账、三号桌、会说话的猫阿账……问到相关词时，Dify 会把 seekdb 里命中的素材交给老巴讲。

## 2. 三项技术怎么分工

| 组件 | 在作品中的实际作用 | 证据 |
| --- | --- | --- |
| **Dify Chatflow** | 应用入口（玩家 ID + 对话）、HTTP 调用 `/recall`、LLM 扮演老巴、HTTP 调用 `/remember`、Answer 输出台词与账本；本次证据是 **Dify Cloud 上已发布应用的真实运行** | `dsl/tavern-memory.chatflow.yml`、`evidence/dify/cloud/*.trace.json`（5 个节点的 Dify 事件） |
| **seekdb 1.4.0（embedded）** | 存放 24 张 lore 素材卡、`players` 账本（欠账/仇怨/来店次数/当前 scope）、`turns` 回合日志；每次 `/recall` 都从 lore 表和账本取数 | `evidence/logs/db_queries.log`（所有 SQL 均标记 `backend=seekdb`）、`evidence/dify/cloud/night*.json` |
| **PowerContext 1.4.1** | 每个玩家一个 scope，`/remember` 用 `POST /v1/memory/remember` 写入本回合叙事，`/recall` 用 `POST /v1/memory/search` 取回旧回合；重启后通过 seekdb 中保存的 `scope_id` 继续使用同一份记忆 | `evidence/logs/powercontext.log`、`evidence/dify/cloud/state-before-night2.json` |

Dify 是编排者；seekdb 是“账本 + 设定库”；PowerContext 是“跨会话的记忆”。三者缺一，第二晚就不会知道第一晚发生了什么。

## 3. 版本与依赖

| 项目 | 版本 / 说明 |
| --- | --- |
| Dify | 提交证据来自 **Dify Cloud 已发布应用**（DSL `version: 0.3.1`）；也可导入自建 Dify 1.18.0 |
| 模型 | 应用内绑定的 Chat 模型（OpenAI 兼容节点）；DSL 中占位为 `langgenius/openai/openai` 的 `gpt-4o-mini`，可换成任意已配置的 Chat 模型（见 4.5） |
| Python | 3.12（后端与 PowerContext 均在 3.12.3 验证） |
| seekdb | `pylibseekdb==1.4.0`（随 `requirements.txt` 安装；仅 Linux x86_64 wheel） |
| PowerContext | `powercontext[server]==1.4.1`，本机 HTTP 模式（默认 `127.0.0.1:8000`，无鉴权） |
| 后端 | FastAPI + uvicorn，`requirements.txt` 已列出 |

> seekdb 以应用数据库（而非 Dify 自身元数据库）的方式参与：Dify 仍使用其默认 PostgreSQL/Redis，酒馆的素材、账本、回合日志全部落在 seekdb。任务允许这种用法，且工作流通过后端实际读写这些数据。

## 4. 从零跑起来

### 4.1 启动 PowerContext

```bash
python3 -m venv ~/tavern-venv
source ~/tavern-venv/bin/activate
pip install -r requirements.txt
# 仅首次需要补一个 PowerContext CLI 依赖（1.4.1 的 extras 未带入）
pip install typer

powercontext server run --role all --host 127.0.0.1 --port 8000
```

保持这个进程运行。验证：

```bash
curl -s http://127.0.0.1:8000/v1/capabilities | head
```

### 4.2 启动酒馆后端

在 **Linux / WSL2 的 ext4 路径**下（不要把 seekdb 数据目录放在 `/mnt/c`）：

```bash
cd dify
export TAVERN_DB_BACKEND=seekdb
export TAVERN_DATA_DIR="$PWD/data"
export TAVERN_LOG_DIR="$PWD/evidence/logs"
export TAVERN_EVIDENCE_DIR="$PWD/evidence"
export POWERCONTEXT_URL=http://127.0.0.1:8000
PY=python3 scripts/start_backend.sh
# 等价于：
# cd backend && python -m uvicorn app:app --host 0.0.0.0 --port 8770
```

首次启动会自动 `CREATE DATABASE tavern`、建表并导入 `backend/lore.json` 的 24 张素材卡。健康检查：

```bash
curl -s http://127.0.0.1:8770/health
# {"ok":true,"db_backend":"seekdb","db_name":"tavern","lore":24,"powercontext":"http://127.0.0.1:8000","powercontext_ok":true}
```

> 后端必须监听 `0.0.0.0`（或至少 Docker 可达的地址），Dify 容器才能访问。只在本机体验时请用防火墙限制 8770 端口。

### 4.3 启动 Dify 并导入 DSL

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
git checkout 1.18.0
cp .env.example .env
docker compose up -d
```

打开 `http://localhost:3000`，完成管理员初始化后：

1. 右上角头像 → **设置 → 模型供应商**，配置一个 Chat 模型（填自己的 API Key）。
2. **工作室 → 创建空白应用 → 导入 DSL 文件**，选择 `dsl/tavern-memory.chatflow.yml`。
3. 打开应用 → 右上角 **环境变量**，把 `TAVERN_API` 改成后端地址：
   - Docker Desktop（Windows/macOS）：`http://host.docker.internal:8770`
   - Linux Docker：给 Dify 的 `api`/`worker` 容器加
     `extra_hosts: ["host.docker.internal:host-gateway"]`，或直接填宿主机局域网 IP。
4. 打开 Chatflow，点开 **老巴（记忆驱动）** LLM 节点，把模型换成你在第 1 步配置的模型（其余提示词不动）。
5. 点 **发布**，然后在 **运行** 页开始新对话。

> 如果 `host.docker.internal` 不可用，可在 Dify 容器里执行
> `docker compose exec api curl -s http://host.docker.internal:8770/health`
> 先确认网络，再改 `TAVERN_API`。

### 4.4 使用 Dify Cloud（本次提交证据的运行方式）

如果不想本地部署 Dify，可以直接在 Dify Cloud 建应用，并让云端访问本机后端：

```bash
# 把本机 8770 暴露为公网 HTTPS（一次性地址，进程退出即失效）
cloudflared tunnel --url http://127.0.0.1:8770
```

1. 在 Dify Cloud 导入 `dsl/tavern-memory.chatflow.yml`（仓库里的
   `evidence/dify/tavern-memory.cloud.yml` 是本次运行用的副本）；
2. 把环境变量 `TAVERN_API` 改成 tunnel 给出的 `https://….trycloudflare.com`；
3. 给 LLM 节点绑定云端已配置的模型，**发布**应用；
4. 从运行页分享链接拿到 app code（`https://udify.app/chat/<code>`），供验证脚本使用。

> tunnel 地址是临时的；重新运行时换成新的地址并重新发布即可。后端本身不需要公网 IP，
> 但 tunnel 期间 8770 可被公网访问，验证完请关掉 cloudflared。

### 4.5 重新绑定模型（可选）

DSL 里的模型只是占位。导入后把 LLM 节点的 `provider/name` 换成本地已配置的任意 Chat 模型即可；提示词中使用的是 `{{#recall_node.body#}}`、`{{#sys.query#}}`，与模型无关。温度建议保持 0.8~0.9。

## 5. 验证：两晚真实 Dify 运行

完整的两段会话、节点轨迹、预期表现和证据索引见 [`docs/verification.md`](docs/verification.md)。最省事的复现方式（需要已发布的 Dify 应用和它的 app code）：

```bash
cd dify
DIFY_APP_CODE=<https://udify.app/chat/ 后面的 code> \
TAVERN_DB_BACKEND=seekdb PY=python3 ./scripts/verify_dify_cloud.sh
```

脚本会：

1. 通过 Dify Web App API 取得 passport，发起流式对话，逐行保存 Dify 的 SSE；
2. 第一晚两轮（赊账、撒谎），采集 `workflow_started` / `node_started` / `node_finished` / `workflow_finished`；
3. **停止后端并重新启动**（`/health` 的 `pid` 随之变化）；
4. 新建 Dify 会话跑第二晚两轮（翻旧账、还账道歉），断言旧账与旧记忆被召回；
5. 每次运行都断言 5 个节点全部 `succeeded`、账本行数字、后端 `app.log` 的 recall/remember 与 seekdb/PowerContext 日志。

提交的运行（2026-11-02）4 次对话全部 5/5 节点成功；第二晚第一轮 `/recall` 命中 2 条旧记忆，后端 `pid` 37705 → 37869，账本从 `欠账 8 / 仇怨 1` 归零。原始 SSE 与节点 trace 在 `evidence/dify/cloud/`。

Dify 界面中的第二晚，账本行应为：

```
—— 老巴的账本：第3次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：闲聊 · 记忆已写入 PowerContext（…）
```

老巴的台词由 LLM 生成，不要求逐字一致，但必须满足：**说出欠 8 币**、**提到上次改口/撒谎**、**至少引用一条旧记忆**。还账后账本必须变成 `欠账 0 币 · 仇怨 0 格`。

> `scripts/verify_two_sessions.sh` + `backend/selftest.py` 是**后端冒烟测试**：用固定 `mock_reply()` 直接调用
> `/recall`、`/remember`，只检查 seekdb/PowerContext 连通性。它不经过 Dify，不作为本赛题“Dify 应用实际执行”的证据；
> 其输出存放在 `evidence/backend-smoke/`。

## 6. 证据与目录

```
dify/
├── dsl/tavern-memory.chatflow.yml   # Dify Chatflow（唯一 DSL，直接导入）
├── backend/
│   ├── app.py                       # /health /recall /remember /state /reset /lore
│   ├── db.py                        # seekdb 存储层（SQL 全量日志）
│   ├── memory.py                    # PowerContext HTTP 客户端
│   ├── tavern.py                    # 赊账/撒谎/偷窃/还账规则
│   ├── selftest.py                  # 后端冒烟测试（不经 Dify，无 LLM Key）
│   └── lore.json                    # 24 张素材卡（原创）
├── scripts/
│   ├── start_backend.sh
│   ├── verify_dify_cloud.py         # 驱动已发布 Dify 应用，保存 SSE/节点 trace/断言
│   ├── verify_dify_cloud.sh         # 两晚 + 后端重启的编排
│   └── verify_two_sessions.sh       # 后端冒烟测试（非 Dify 证据）
├── docs/
│   ├── verification.md              # 两晚 Dify 运行、预期、证据索引
│   └── TECH.md                      # 一页技术说明
└── evidence/
    ├── dify/cloud/                  # 4 次 Dify 运行的原始 SSE、节点 trace、断言、health
    ├── logs/                        # 本次 Dify 运行的后端日志（seekdb / PowerContext）
    └── backend-smoke/               # 后端接口级冒烟测试（不经过 Dify）
```

`evidence/dify/cloud/*.sse.txt` 是 Dify 直接返回的原始事件流；`*.trace.json` 保存了节点表、`workflow_run_id`、
Answer、后端日志增量与 `/state`。`evidence/logs/db_queries.log` 中每一行都是 seekdb 上真实执行的 SQL
（`backend=seekdb`）；`powercontext.log` 记录了 scope 创建/复用、remember 与 search 的命中数（0→4）。
`evidence/dify/tavern-memory.cloud.yml` 是导入 Dify Cloud 时用的 DSL 副本（`TAVERN_API` 为一次性 tunnel 地址）。

## 7. 重置与重复验证

- **只重置某个玩家**：
  ```bash
  curl -s -X POST http://127.0.0.1:8770/reset \
    -H 'Content-Type: application/json' -d '{"player_id":"alice"}'
  ```
  账本与回合清零；epoch +1，PowerContext 换一个带随机后缀的新 scope，旧记忆不再参与。
- **完全重置**：停止后端，删除 `data/`（seekdb 数据目录）后重启；素材卡会自动重新导入。
- `verify_dify_cloud.py night1` 每次都会先调用 `/reset`，可直接重复执行；重复执行不会污染旧 scope。`night2` 不重置，以保留第一晚状态供跨进程召回。

## 8. 已知限制

- `pylibseekdb` 只有 Linux x86_64 wheel，因此 seekdb 版后端必须跑在 Linux/WSL2；Windows 原生只能使用 `TAVERN_DB_BACKEND=sqlite` 做冒烟测试（不用于提交证据）。
- 单进程后端（seekdb 句柄与内存锁不跨进程）；不要用多个 uvicorn worker。
- PowerContext 默认无鉴权且记忆检索为文本模式；本作品记忆链很短，未引入 Embedding/Rerank。若长期运行，建议启用鉴权并清理旧 epoch。
- 老巴台词由 LLM 生成，存在措辞波动；账本数字与规则完全由后端决定，可用账本行核对。若模型不肯提旧账，可将温度降到 0.7 或换更强的模型。
- Dify Web App 的流式事件默认隐藏节点的 inputs/outputs（控制台 API 才可读）。本仓库的证据因此由
  Dify 的 `node_id`/状态/耗时、`workflow_finished.outputs.answer`，以及后端在同一秒内新增的
  recall/remember 日志交叉证明；原始 SSE 一并提交，未做改写。
- 使用 Dify Cloud 时，`TAVERN_API` 需要公网可达（cloudflared 等 tunnel）。tunnel 地址是一次性的，
  验证后应关闭；后端与 PowerContext 均按本地可信环境设计，请勿长期直接暴露到公网。
- 后端与 PowerContext 均按本地可信环境设计，未做公网鉴权；请勿直接暴露到公网。

## 9. 来源与声明

- 素材、人物、价格、店规均为本作品原创；未复用公开工作流或第三方数据集。
- Dify DSL 的节点字段按 Dify 1.18.0 导出的 `0.3.1` 结构编写，并参考了 Dify 官方测试夹具 `api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml`、`basic_chatflow.yml` 的字段组织方式。
- PowerContext 与 seekdb 的接入均使用其公开版本与文档 API，版本已在第 3 节列明。
