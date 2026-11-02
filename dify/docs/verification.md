# 验证样例：两晚之后，老巴还记得（真实 Dify 运行）

本样例证明的是**应用层**行为，而不是只有后端接口：

1. 已发布的 Dify Chatflow 真的跑完 5 个节点：Start → 回忆旧账 → 老巴（LLM）→ 记账与存忆 → Answer；
2. 每次运行都有 Dify 自己产生的 `workflow_started` / `node_started` / `node_finished` / `workflow_finished` 事件与 `workflow_run_id`；
3. 两个 HTTP 节点真的到达后端，seekdb 保存并返回素材与账本（欠账 8、仇怨 1）；
4. PowerContext 保存第一晚的两条情节记忆，并在**后端重启 + 新 Dify 会话**后检索出来；
5. 规则结算可复现：还账并道歉后，账本归零。

## 0. 运行环境与初始状态

本次提交的证据在 2026-11-02 11:40–11:41 生成：

| 项目 | 值 |
| --- | --- |
| Dify | Dify Cloud 已发布应用 `https://udify.app/chat/rb4J4mx8dCdy4isV`，DSL `tavern-memory.chatflow.yml`（`version: 0.3.1`） |
| LLM | Dify 应用中绑定的 Chat 模型（OpenAI 兼容节点），台词由模型生成 |
| 后端到 Dify 的通道 | Cloudflare quick tunnel → 本机 `127.0.0.1:8770` |
| 后端 | FastAPI + uvicorn，`TAVERN_DB_BACKEND=seekdb`，Python 3.12（WSL2 Ubuntu） |
| seekdb | `pylibseekdb==1.4.0`，库名 `tavern` |
| PowerContext | 1.4.1，`http://127.0.0.1:8000` |
| 玩家 ID | `demo_alice`（两晚必须一致） |

初始状态：seekdb 空库，首次启动导入 `lore` 24 行，`players` / `turns` 为空；PowerContext 无 `demo_alice` 的 scope。

## 1. 第一晚（Dify 新会话 A）

在 Dify 运行页新建会话，开始节点填 `demo_alice`。

### 1.1 赊一杯火焰威士忌

输入：

```
老巴，来杯火焰威士忌，先记我账上，明天还你。
```

本次运行的 Dify 节点轨迹（`evidence/dify/cloud/night1-turn1.trace.json`）：

| # | node_id | 节点 | 类型 | 状态 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 1 | `start_node` | Start | start | succeeded | 0.0001s |
| 2 | `recall_node` | 回忆旧账（seekdb + PowerContext） | http-request | succeeded | 0.7366s |
| 3 | `llm_node` | 老巴（记忆驱动） | llm | succeeded | 8.6272s |
| 4 | `remember_node` | 记账与存忆（seekdb + PowerContext） | http-request | succeeded | 0.5342s |
| 5 | `answer_node` | Answer | answer | succeeded | 0.0001s |

`workflow_finished.status=succeeded`、`total_steps=5`，`workflow_run_id=e38c553c-e36c-40da-ac30-f70887a79146`。
Answer 末尾的账本行：

```
—— 老巴的账本：第1次照面 · 欠账 8 币 · 仇怨 0 格 · 本回合：赊账（赊下火焰威士忌（8 币）） · 记忆已写入 PowerContext（scp_20a135tw…）
```

后端同时发生（`evidence/logs/app.log`、`db_queries.log`）：

```
11:40:59  recall    player=demo_alice visits=0 debt=0 grudge=0 lore=3 memories=0
11:41:08  remember  player=demo_alice intent=credit delta_debt=8 delta_grudge=0 debt=8 grudge=0 memory=ok
```

seekdb 执行 `INSERT INTO turns (... 'credit', 8, 0)` 与 `UPDATE players SET visits=1, debt=8, grudge=0`；PowerContext 执行 `POST /v1/memory/remember`（第 1 条情节记忆）。

### 1.2 改口（撒谎）

输入：

```
我昨天说的是下周还，你可别记错了。
```

同一条 Dify 会话，节点轨迹同为 5/5 succeeded（`night1-turn2.trace.json`，`workflow_run_id=c48eed7b-6fd4-495e-a599-c6a76ce9cf9c`），账本行：

```
—— 老巴的账本：第2次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：撒谎（被假眼识破，记仇一格） · 记忆已写入 PowerContext（scp_20a135tw…）
```

后端：

```
11:41:11  recall    player=demo_alice visits=1 debt=8 grudge=0 lore=2 memories=1
11:41:18  remember  player=demo_alice intent=lie delta_debt=0 delta_grudge=1 debt=8 grudge=1 memory=ok
```

### 1.3 第一晚结束状态

`/state`：`visits=2, debt=8, grudge=1`，PowerContext 命中 2 条记忆，`turns` 表 2 行。

**重启后端**（证明状态不在进程内存里）。提交的运行里：

- 第一晚进程：`pid=37705`，`started_at=2026-11-02T11:40:51`（`health-night1.json`）；
- 第二晚进程：`pid=37869`，`started_at=2026-11-02T11:41:20`（`health-night2.json`）。

## 2. 第二晚（Dify 新会话 B）

在 Dify 中**新建会话**（`conversation_id=fae80759-1b5f-4b0a-81c5-9b920f4376c2`），玩家 ID 仍填 `demo_alice`。

### 2.1 老巴翻旧账

输入：

```
老巴，我又来了，今天有什么好酒？
```

Dify 节点轨迹仍是 5/5 succeeded（`night2-turn1.trace.json`，`workflow_run_id=8be9be2f-96f5-4a01-b6b9-443223ba3bb8`）。老巴的台词（模型生成）：

```
老巴抬眼：“又来了？你还欠八枚币。上回说‘明天还’，隔天就改成‘下周还’，我还记着你一格仇呢。
好酒是月光艾尔，五枚币一杯，银色泡沫，喝了会想起初恋。旧账先清，还是拿故事抵利息？”
```

账本行：

```
—— 老巴的账本：第3次照面 · 欠账 8 币 · 仇怨 1 格 · 本回合：闲聊 · 记忆已写入 PowerContext（scp_20a135tw…）
```

跨进程、跨会话的直接证据：

- 新进程启动后 `/health` 的 `pid` 从 37705 变为 37869；
- `/state` 仍返回 `visits=2, debt=8, grudge=1`，`memories>=2`；
- `powercontext.log` 在重启后继续 `reuse ... scope_id=scp_20a135twrvy3f0ncw9pzw3tp6p`，检索 `hits=2`；
- 后端 `app.log`：`11:41:25 recall player=demo_alice visits=2 debt=8 grudge=1 ... memories=2`。

### 2.2 还账并道歉

输入：

```
对不起，上次是我不对。我这就还你 8 币。
```

`night2-turn2.trace.json`，`workflow_run_id=4117deec-f729-42fb-ac1a-320a4ea1c310`，5/5 succeeded。账本行：

```
—— 老巴的账本：第4次照面 · 欠账 0 币 · 仇怨 0 格 · 本回合：还账并道歉（收下 8 币，并接受了道歉） · 记忆已写入 PowerContext（scp_20a135tw…）
```

后端：`intent=repay_apology, delta_debt=-8, delta_grudge=-1`；最终 `/state` 为 `visits=4, debt=0, grudge=0`，PowerContext 4 条记忆。

## 3. 复现命令（驱动真实 Dify）

`scripts/verify_dify_cloud.sh` 不再调用 `/recall`、`/remember` 代替应用，而是像浏览器一样调用**已发布的 Dify Web 应用**：

1. `GET /api/passport`（`X-App-Code`）取得 app passport；
2. `POST /api/chat-messages`（`X-App-Passport`，`response_mode=streaming`）发起对话；
3. 逐行消费 SSE，保存 Dify 的 `workflow_*` / `node_*` 事件；
4. 断言 5 个节点、`workflow_run_id`、账本行、后端日志、`/state`；
5. 在两次运行之间**重启后端**。

```bash
# 1. 已发布应用可通过公网访问后端：把本机 8770 暴露出去，并写入 Dify 的 TAVERN_API
cloudflared tunnel --url http://127.0.0.1:8770

# 2. 两晚验证（会启动/停止后端两次，并写入 evidence/dify/cloud/）
cd dify
DIFY_APP_CODE=<https://udify.app/chat/ 后面的 code> \
TAVERN_DB_BACKEND=seekdb \
PY=python3 ./scripts/verify_dify_cloud.sh
```

成功时每次运行都会打印 5 个节点的 `succeeded` 和 `[ok]` 断言，最终两晚均为 `PASS`。

如果 Dify 与后端在同一台机器/同一 Docker 网络，可省略 tunnel，把 DSL 的 `TAVERN_API` 设为
`http://host.docker.internal:8770`（Docker Desktop）或后端服务名，然后同样执行上面的脚本（脚本只要求 `DIFY_APP_CODE`）。

### 3.1 单看某一晚

```bash
export DIFY_APP_CODE=... DIFY_EVIDENCE_DIR=evidence/dify/cloud
python3 scripts/verify_dify_cloud.py night1
# 重启后端
python3 scripts/verify_dify_cloud.py night2
```

`night1` 会先调用 `/reset`，因此脚本可重复运行：seekdb 账本清零、epoch+1，PowerContext 换新 scope，旧记忆不参与。

### 3.2 后端冒烟测试（不是本赛题的证据）

`scripts/verify_two_sessions.sh` + `backend/selftest.py` 用固定 `mock_reply()` 直接调用 `/recall`、`/remember`，
只用于在**没有 LLM Key/Dify 环境**时快速检查 seekdb 与 PowerContext 的连接；其输出保存在
`evidence/backend-smoke/`。它不经过 Dify，**不能**作为本赛题“Dify 应用实际执行”的证据。

## 4. 已提交的实际运行记录

| 证据 | 内容 |
| --- | --- |
| `evidence/dify/cloud/night1-turn1.sse.txt` … `night2-turn2.sse.txt` | 4 次运行的**原始 SSE 字节流**（Dify 直接返回） |
| `evidence/dify/cloud/night1-turn1.trace.json` … | 每次运行的完整事件、节点表、Answer、后端日志增量、`/state`、逐条断言 |
| `evidence/dify/cloud/night1-turn1.events.json` … | 解析后的 Dify 事件数组（便于机读） |
| `evidence/dify/cloud/night1.json` / `night2.json` | 两晚的汇总：41 + 47 条断言全部 `ok`，`workflow_run_id`、会话 ID、最终账本 |
| `evidence/dify/cloud/health-night1.json` / `health-night2.json` | 两次进程的 `/health`，`pid` 37705 → 37869 |
| `evidence/dify/cloud/state-before-night2.json` | 重启后、第二晚开始前的 `/state`（debt=8, grudge=1, memories=2） |
| `evidence/logs/app.log` | 两次 `start backend=seekdb`、4 轮 recall/remember（含 `memories=2` 的跨会话召回） |
| `evidence/logs/db_queries.log` | seekdb 上真实执行的 97 条语句：建表、导入 24 卡、`INSERT turns`、`UPDATE players`、`SELECT` |
| `evidence/logs/powercontext.log` | scope 创建、4 次 remember、search 命中 0→1→2→3→4，重启后 `reuse` 同一 scope |
| `evidence/logs/server-night1.log` / `server-night2.log` | 两个后端进程的 uvicorn 请求日志 |

四次运行的 `workflow_run_id`：

| 运行 | workflow_run_id | Dify conversation_id |
| --- | --- | --- |
| 第一晚 · 赊账 | `e38c553c-e36c-40da-ac30-f70887a79146` | `ba7608d9-7ef7-4eaa-b918-ebd6cdc66ca6` |
| 第一晚 · 撒谎 | `c48eed7b-6fd4-495e-a599-c6a76ce9cf9c` | `ba7608d9-7ef7-4eaa-b918-ebd6cdc66ca6` |
| 第二晚 · 翻旧账 | `8be9be2f-96f5-4a01-b6b9-443223ba3bb8` | `fae80759-1b5f-4b0a-81c5-9b920f4376c2` |
| 第二晚 · 还账 | `4117deec-f729-42fb-ac1a-320a4ea1c310` | `fae80759-1b5f-4b0a-81c5-9b920f4376c2` |

### 4.1 自己抽查节点轨迹

```bash
cd dify/evidence/dify/cloud
# 每次运行都是 5 个节点、全部 succeeded
jq -r '.nodes_finished[] | "\(.index) \(.node_id) \(.node_type) \(.status) \(.elapsed_time)s"' night2-turn1.trace.json
# Dify 的原始事件里也有同样的节点（不依赖本脚本的解析）
grep -o '"event": "[a-z_]*"' night2-turn1.events.json | sort | uniq -c
```

`node_finished` 事件由 Dify 产生并随 SSE 返回；脚本只是保存和断言，没有伪造节点。

## 5. Dify 界面截图/录屏建议（提交前补齐）

1. 应用运行页第一晚两条消息 + 两次账本行；
2. 新建会话后第二晚第一条回复（必须出现 8 币与旧事）；
3. 还账后账本行归零；
4. Dify 工作流画布（5 个节点：Start → 回忆旧账 → 老巴 → 记账与存忆 → Answer）；
5. 后端终端 `/health`（`pid` 变化）与 `db_queries.log` 的 `backend=seekdb` 行。

截图不替代本文件与 `evidence/` 中的可复现材料，只作为界面层补充。

## 6. 重置

- 单个玩家：`POST /reset {"player_id":"demo_alice"}`，账本/回合清零，epoch+1，PowerContext 换新 scope。
- 完全重置：停止后端，删除 seekdb 数据目录（默认 `dify/data/`）后重启，素材卡自动重新导入。
- 脚本 `verify_dify_cloud.py night1` 会自动重置；`night2` 不重置，以保留第一晚状态。
