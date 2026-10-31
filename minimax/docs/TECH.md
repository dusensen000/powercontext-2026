# 一页技术说明

## 模块结构

```
sddctx/
  ingest.py     规格按 "## " 切块、代码/测试用 ast 切到函数/类，记录 path/req_id/symbol/lineno
  db.py         seekdb(嵌入式, PyMySQL) 单表 eng_docs；LIKE 召回后按关键词命中数排序
  context.py    任务 → ASCII token + 中文 bigram 关键词 → 分别取 spec/code/test → 有界上下文
  minimax_client.py  提示词组装；官方 / OpenAI 兼容 HTTP；从回复中提取 unified diff
  agent.py      在 .work/sample 副本上 git apply / patch / 纯 Python 回退；pytest；失败反馈重试(≤3)
  state.py      PowerContext remember/search 保存读取；scope 自动创建并缓存
  verify.py     12 步端到端验收，输出 artifacts/report.json
  cli.py        ingest / context / run-agent / test / state-load / demo
```

## 上下文如何选择

1. 任务文本抽词：`[A-Za-z_][A-Za-z0-9_]{2,}` 与中文二元组，限制 60 个。
2. 三类资料分别查询：`SELECT ... WHERE kind=? AND (text LIKE ? OR path LIKE ? OR symbol LIKE ?)`，参数化绑定。
3. 结果按关键词在 `text/path/symbol/req_id` 中的命中次数降序；模块级整文件块排到具体符号之后，最多各取 6 条。
4. 输出包含 `specs/code/tests` 与 `sources`（真实路径、行号、测试节点 ID），便于核对来源。
5. 规格变更后重新 `ingest`（先 `DELETE` 再批量插入），下次检索即使用新内容；演进场景写入独立数据库 `sddctx_evolve`，避免污染原索引。

## 三项技术的分工

| 技术 | 实际承担的工作 | 可核对证据 |
| --- | --- | --- |
| seekdb | 持久化规格/代码/测试切块；所有检索 SQL 都来自它，结果直接决定上下文内容 | `artifacts/db_queries.log`、`sddctx/db.py` |
| MiniMax | 读取上下文与当前源码，产出 unified diff；失败时读取 pytest 输出重试 | `artifacts/prompts/attempt*.json`、`artifacts/dev_record.json`、`artifacts/diff.patch` |
| PowerContext | 保存任务状态（已完成/待办/变更文件/验证结果）；新进程 `state-load` 读回，并注入下一任务上下文 | `artifacts/state_ops.log`、`artifacts/context_resume.md` |

## 关键设计

- **可复核性优先**：每个阶段都落盘，测试日志记录命令、退出码、源码哈希与（若在仓库内）commit。
- **隔离执行**：在 `.work/sample` 副本上修改，样例源文件保持干净，重复运行结果稳定。
- **失败可重试**：应用失败或测试失败时，把 stderr/pytest 输出回灌给模型，最多 3 轮。
- **状态与代码解耦**：状态存 PowerContext，进程重启或换 Agent 后仍可恢复；本轮只要求恢复任务记录，不恢复完整会话。
- **降级路径**：没有 seekdb 时可用 sqlite；没有 PowerContext 时可用 local 文件；没有模型密钥时可用 `stub` 回放补丁。降级仅用于联调，验收使用 seekdb + PowerContext + MiniMax。
