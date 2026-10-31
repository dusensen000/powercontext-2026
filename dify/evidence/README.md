# 证据索引

本目录由 `scripts/verify_two_sessions.sh` 在 WSL2（Ubuntu 24.04）上生成，环境为
`pylibseekdb==1.4.0` + PowerContext 1.4.1 + Python 3.12.3，数据库为 seekdb。

| 文件 | 证明什么 |
| --- | --- |
| `session1.log` / `session2.log` | 两段会话的终端输出与 `[ok]` 断言 |
| `session1.json` / `session2.json` | 每轮 `/recall` 的完整上下文、账本行、最终 `/state` |
| `logs/db_queries.log` | seekdb 实际执行的全部 SQL（每行 `backend=seekdb`） |
| `logs/powercontext.log` | scope 创建/复用、memory remember/search 及命中数 |
| `logs/app.log` | 后端两次启动、每轮 recall/remember 的摘要 |
| `logs/server-session*.log` | 两个后端进程的 HTTP 请求日志 |
| `health-session*.json` | 两次启动的 `/health` |

复现：在 `dify/` 下执行 `PY=python3 TAVERN_DB_BACKEND=seekdb ./scripts/verify_two_sessions.sh`。
脚本每次先 `/reset`，可重复运行；seekdb 数据写入 `data/`，不属于提交物。
