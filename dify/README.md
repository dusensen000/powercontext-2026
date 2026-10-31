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
| **Dify 1.18.0 Chatflow** | 应用入口（玩家 ID + 对话）、HTTP 调用 `/recall`、LLM 扮演老巴、HTTP 调用 `/remember`、Answer 输出台词与账本 | `dsl/tavern-memory.chatflow.yml` |
| **seekdb 1.4.0（embedded）** | 存放 24 张 lore 素材卡、`players` 账本（欠账/仇怨/来店次数/当前 scope）、`turns` 回合日志；每次 `/recall` 都从 lore 表和账本取数 | `evidence/logs/db_queries.log`（所有 SQL 均标记 `backend=seekdb`） |
| **PowerContext 1.4.1** | 每个玩家一个 scope，`/remember` 用 `POST /v1/memory/remember` 写入本回合叙事，`/recall` 用 `POST /v1/memory/search` 取回旧回合；重启后通过 seekdb 中保存的 `scope_id` 继续使用同一份记忆 | `evidence/logs/powercontext.log`、`evidence/session2.json` |

Dify 是编排者；seekdb 是“账本 + 设定库”；PowerContext 是“跨会话的记忆”。三者缺一，第二晚就不会知道第一晚发生了什么。

## 3. 版本与依赖

| 项目 | 版本 / 说明 |
| --- | --- |
| Dify | **1.18.0**（官方 docker compose 部署；DSL `version: 0.3.1`） |
| 模型 | DSL 中占位为 `langgenius/openai/openai` 的 `gpt-4o-mini`；可换成任意已配置的 Chat 模型（见 4.4） |
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

### 4.4 重新绑定模型（可选）

DSL 里的模型只是占位。导入后把 LLM 节点的 `provider/name` 换成本地已配置的任意 Chat 模型即可；提示词中使用的是 `{{#recall_node.body#}}`、`{{#sys.query#}}`，与模型无关。温度建议保持 0.8~0.9。

## 5. 验证样例

完整的两段会话脚本、预期表现和证据索引见 [`docs/verification.md`](docs/verification.md)。最省事的复现方式：

```bash
cd dify
PY=python3 TAVERN_DB_BACKEND=seekdb ./scripts/verify_two_sessions.sh
```

脚本会：启动后端 → 跑第一晚（赊账 + 撒谎）→ **停止后端** → 重新启动 → 跑第二晚（旧账被翻出 + 还账道歉）→ 断言 seekdb 账本和 PowerContext 记忆。成功时以 `[ok]` 结尾，并在 `evidence/` 下生成 JSON 与日志。

Dify 界面中的第二晚，账本行应为：

```
—— 老巴的账本：第3次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：闲聊 · 记忆已写入 PowerContext（…）
```

老巴的台词由 LLM 生成，不要求逐字一致，但必须满足：**说出欠 8 币**、**提到上次改口/撒谎**、**至少引用一条旧记忆**。还账后账本必须变成 `欠账 0 币 · 仇怨 0 格`。

## 6. 证据与目录

```
dify/
├── dsl/tavern-memory.chatflow.yml   # Dify Chatflow（唯一 DSL，直接导入）
├── backend/
│   ├── app.py                       # /health /recall /remember /state /reset /lore
│   ├── db.py                        # seekdb 存储层（SQL 全量日志）
│   ├── memory.py                    # PowerContext HTTP 客户端
│   ├── tavern.py                    # 赊账/撒谎/偷窃/还账规则
│   ├── selftest.py                  # 两段会话验证（无需 LLM Key）
│   └── lore.json                    # 24 张素材卡（原创）
├── scripts/
│   ├── start_backend.sh
│   └── verify_two_sessions.sh
├── docs/
│   ├── verification.md              # 验证样例、预期、重置
│   └── TECH.md                      # 一页技术说明
└── evidence/
    ├── session1.json / session2.json
    ├── session1.log / session2.log
    └── logs/                        # db_queries.log / powercontext.log / app.log / server-*.log
```

`evidence/session1.json` 与 `session2.json` 保存了每一步 `/recall` 的完整返回（含 `lore`、`memories`、`ledger_tail`）、模拟台词、账本行以及最终的 `/state`。`evidence/logs/db_queries.log` 中每一行都是 seekdb 上真实执行的 SQL（`backend=seekdb`）；`powercontext.log` 记录了 scope 创建/复用、remember 与 search 的命中数。

## 7. 重置与重复验证

- **只重置某个玩家**：
  ```bash
  curl -s -X POST http://127.0.0.1:8770/reset \
    -H 'Content-Type: application/json' -d '{"player_id":"alice"}'
  ```
  账本与回合清零；epoch +1，PowerContext 换一个带随机后缀的新 scope，旧记忆不再参与。
- **完全重置**：停止后端，删除 `data/`（seekdb 数据目录）后重启；素材卡会自动重新导入。
- `verify_two_sessions.sh` 每次都会先调用 `/reset`，可直接重复执行；重复执行不会污染旧 scope。

## 8. 已知限制

- `pylibseekdb` 只有 Linux x86_64 wheel，因此 seekdb 版后端必须跑在 Linux/WSL2；Windows 原生只能使用 `TAVERN_DB_BACKEND=sqlite` 做冒烟测试（不用于提交证据）。
- 单进程后端（seekdb 句柄与内存锁不跨进程）；不要用多个 uvicorn worker。
- PowerContext 默认无鉴权且记忆检索为文本模式；本作品记忆链很短，未引入 Embedding/Rerank。若长期运行，建议启用鉴权并清理旧 epoch。
- 老巴台词由 LLM 生成，存在措辞波动；账本数字与规则完全由后端决定，可用账本行核对。若模型不肯提旧账，可将温度降到 0.7 或换更强的模型。
- 后端与 PowerContext 均按本地可信环境设计，未做公网鉴权；请勿直接暴露到公网。

## 9. 来源与声明

- 素材、人物、价格、店规均为本作品原创；未复用公开工作流或第三方数据集。
- Dify DSL 的节点字段按 Dify 1.18.0 导出的 `0.3.1` 结构编写，并参考了 Dify 官方测试夹具 `api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml`、`basic_chatflow.yml` 的字段组织方式。
- PowerContext 与 seekdb 的接入均使用其公开版本与文档 API，版本已在第 3 节列明。
