# 验证样例：TaskBoard 状态筛选（REQ-003）

本样例用于验证 SDD 上下文模块的完整闭环：检索当前有效规格 → 相关代码与测试 → MiniMax 修改 → 目标测试由失败转通过 → 回归测试保持通过 → 任务进展保存并在重启后继续使用。

## 1. 任务描述（要改什么）

> 为 `list_tasks` 增加按 `status` 筛选的能力：`status` 非空时只返回该状态的任务，`None` 时返回全部；筛选必须在排序和分页之前完成，且不能破坏既有的排序、分页与输入校验行为。

## 2. 当前有效规格

来源：`sample/specs/taskboard.md`

| 规格 | 内容 | 与本次任务的关系 |
| --- | --- | --- |
| REQ-001 | 按 `(due_date, id)` 升序 | 必须保持 |
| REQ-002 | 先排序，再按 `limit/offset` 分页 | 必须保持；筛选要在分页前 |
| **REQ-003** | `status` 非空时只返回相等任务；筛选在排序与分页之前 | **本次要实现的规格** |
| REQ-004 | `limit` 正整数、`offset >= 0`，否则 `ValueError` | 必须保持 |

## 3. 初始数据

`sample/tests/test_target_filter.py` 与 `sample/tests/test_regression.py` 共用固定数据：

| id | title | status | due_date |
| --- | --- | --- | --- |
| 1 | Write report | active | 2026-05-01 |
| 2 | Review PR | done | 2026-05-02 |
| 3 | Fix bug | active | 2026-05-02 |
| 4 | Plan sprint | done | 2026-05-03 |
| 5 | Deploy | active | 2026-05-04 |

初始 `sample/src/taskboard/service.py` 中 `list_tasks` 未实现筛选，仅有 `# TODO(REQ-003)` 占位。

## 4. 上下文中必须包含的来源

模块对上述任务输出的上下文（`artifacts/context.json`）必须命中以下真实来源：

| 类型 | 来源 |
| --- | --- |
| 规格 | `specs/taskboard.md` → `REQ-003`（同时应命中 REQ-001/002/004） |
| 代码 | `src/taskboard/service.py` → `list_tasks` |
| 测试 | `tests/test_target_filter.py::test_filter_active_only` |
| 测试 | `tests/test_target_filter.py::test_filter_then_sort_and_paginate` |
| 测试 | `tests/test_regression.py::test_sorts_by_due_date_then_id` 等回归用例 |

## 5. 操作步骤

```bash
cd minimax
pip install -r requirements.txt
export MINIMAX_API_KEY=...            # 验收时填真实密钥；离线冒烟可用 SDDCTX_PROVIDER=stub
python -m sddctx demo                 # 一键端到端；分步命令见 README 第 4 节
```

`demo` 会创建独立工作副本 `.work/sample`（从 `sample/` 复制），不会修改样例源文件。

## 6. 预期结果

| 阶段 | 命令 | 预期 |
| --- | --- | --- |
| 上下文 | `python -m sddctx context --write` | `artifacts/context.json` 中含上表全部来源 |
| 修改前 | pytest `tests/test_target_filter.py` | `2 failed`（`[1,3,5]` 与 `[1,3]` 断言失败，属功能缺失而非环境错误） |
| MiniMax | `python -m sddctx run-agent` | 返回 unified diff 并成功应用，`artifacts/dev_record.json` 与 `artifacts/diff.patch` 对应 |
| 修改后 | pytest `tests/test_target_filter.py` | `2 passed` |
| 回归 | pytest `tests/test_regression.py` | `5 passed` |
| 状态复用 | `demo` 中独立进程 `python -m sddctx state-load` | 读回 `taskboard-status-filter`，`status=done` |
| 状态使用 | `demo` 中 `context_resume.md` | 下一个任务的上下文包含“上一轮任务进展”与待办项 |
| 规格演进 | `demo` 中重新入库 `REQ-005` | 新任务检索结果 `REQ-005` 排第一，旧索引不受污染 |

## 7. 规格演进场景（REQ-005）

仓库中预置了演进规格 `sample/specs_phase2/taskboard-phase2.md`（不参与默认入库），内容为：

```
## REQ-005 优先级排序
list_tasks 需要支持按 priority 降序排序；priority 相同时保持既有的 due_date, id 升序规则。
排序仍必须在状态筛选之后、分页之前完成。
```

`demo` 会把它复制到演进副本的 `specs/` 并重新入库到独立数据库 `sddctx_evolve`。任务「为 list_tasks 增加按 priority 降序排序」的上下文首条规格切换为 REQ-005，证明输出随规格更新而变化，而不是固定答案。

## 8. 重置方法

```bash
cd minimax
rm -rf .work .data artifacts/report.json artifacts/context*.json artifacts/context*.md \
       artifacts/diff.patch artifacts/dev_record.json artifacts/prompts \
       artifacts/test_logs/*.log artifacts/db_queries.log artifacts/state_ops.log
python -m sddctx demo
```

`.data/` 保存 seekdb 数据目录与本地状态，删除即回到空状态；PowerContext 侧在全新 Server 上天然为空。
