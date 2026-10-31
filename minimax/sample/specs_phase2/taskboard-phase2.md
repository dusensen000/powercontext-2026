# 任务板二期规格

## REQ-005 优先级排序

`list_tasks` 需要支持按 `priority` 降序排序；`priority` 相同时保持既有的
`due_date, id` 升序规则。排序仍必须在状态筛选之后、分页之前完成。
