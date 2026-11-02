# 证据索引

## 1. Dify 真实运行（本赛题的核心证据）

由 `scripts/verify_dify_cloud.sh` 生成：它通过 Dify Web App API 驱动**已发布的 Chatflow**，
两晚之间重启后端，并保存 Dify 返回的原始 SSE 与节点事件。

| 文件 | 证明什么 |
| --- | --- |
| `dify/cloud/night1-turn1.sse.txt` … `night2-turn2.sse.txt` | 4 次对话的原始 SSE 字节流（含 `workflow_started` / `node_started` / `node_finished` / `workflow_finished`） |
| `dify/cloud/*.trace.json` | 每次运行的节点表（5/5 succeeded）、`workflow_run_id`、Answer、后端日志增量、`/state`、逐条断言 |
| `dify/cloud/*.events.json` | 解析后的 Dify 事件数组 |
| `dify/cloud/night1.json` / `night2.json` | 两晚汇总（41 + 47 条断言全部通过） |
| `dify/cloud/health-night1.json` / `health-night2.json` | 两次进程的 `/health`，`pid` 37705 → 37869，证明后端重启 |
| `dify/cloud/state-before-night2.json` | 重启后、第二晚开始前的 `/state`：debt=8、grudge=1、memories=2 |
| `logs/app.log` | 两晚的 recall/remember 摘要；第二晚第一条 `recall ... memories=2` 即跨会话召回 |
| `logs/db_queries.log` | seekdb 真实执行的 97 条 SQL（均带 `backend=seekdb`） |
| `logs/powercontext.log` | scope 创建/复用、4 次 remember、search 命中 0→4 |
| `logs/server-night1.log` / `server-night2.log` | 两个后端进程的请求日志 |

复现：

```bash
cd dify
DIFY_APP_CODE=<code from https://udify.app/chat/...> \
TAVERN_DB_BACKEND=seekdb PY=python3 ./scripts/verify_dify_cloud.sh
```

云端 Dify 需要能访问本机后端：先用 `cloudflared tunnel --url http://127.0.0.1:8770` 暴露端口，
并把 `TAVERN_API` 设成该 tunnel 地址。自建 Dify 可直接用 `host.docker.internal:8770`。

## 2. 后端冒烟测试（仅用于无 Dify 环境自查，不作为本赛题证据）

`backend-smoke/` 由 `scripts/verify_two_sessions.sh` 生成。它直接调用 `/recall`、`/remember`，
台词是固定 `mock_reply()`，**不经过 Dify**，只用于检查 seekdb + PowerContext 是否连通。

| 文件 | 证明什么 |
| --- | --- |
| `backend-smoke/session1.log` / `session2.log` | 后端接口级两段会话与 `[ok]` 断言 |
| `backend-smoke/session1.json` / `session2.json` | 每轮 `/recall` 的完整返回、账本行、最终 `/state` |
| `backend-smoke/app.log` / `db_queries.log` / `powercontext.log` | 该次冒烟测试的后端日志 |

复现：`PY=python3 TAVERN_DB_BACKEND=seekdb ./scripts/verify_two_sessions.sh`。

`dify/tavern-memory.cloud.yml` 是用于导入 Dify Cloud 的 DSL 副本，其中 `TAVERN_API` 指向当次使用的 tunnel。
tunnel 地址是一次性的；重新跑时替换成自己的地址即可（`dsl/tavern-memory.chatflow.yml` 保持 `host.docker.internal`）。
