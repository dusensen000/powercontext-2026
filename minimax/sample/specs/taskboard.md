# TaskBoard 规格说明

本文件是 TaskBoard 服务的有效规格。需求编号 REQ-* 用于在开发上下文与测试之间建立可追溯关系。

## REQ-001 列表排序

`list_tasks` 返回的任务必须按 `due_date` 升序排列；`due_date` 相同时按 `id` 升序排列。

## REQ-002 分页

`list_tasks` 支持 `limit` 与 `offset` 参数：先完成排序，再进行分页切分，最后返回当前页。

## REQ-003 按状态筛选（目标需求）

`list_tasks` 必须支持 `status` 参数：

- 当 `status` 为非空字符串时，只返回 `status` 字段与之相等的任务。
- 当 `status` 为 `None` 时，返回全部任务。
- 状态筛选必须在排序与分页之前完成，保证分页结果只包含符合条件的任务。

## REQ-004 输入校验

- `limit` 必须是正整数，否则抛出 `ValueError`。
- `offset` 必须大于等于 0，否则抛出 `ValueError`。
