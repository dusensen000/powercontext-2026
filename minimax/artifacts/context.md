# 开发上下文

## 任务
为 list_tasks 增加按 status 筛选的能力：status 非空时只返回该状态的任务，None 时返回全部；筛选必须在排序和分页之前完成，且不能破坏既有的排序、分页与输入校验行为。

## 适用规格
### REQ-003  (specs/taskboard.md)
## REQ-003 按状态筛选（目标需求）

`list_tasks` 必须支持 `status` 参数：

- 当 `status` 为非空字符串时，只返回 `status` 字段与之相等的任务。
- 当 `status` 为 `None` 时，返回全部任务。
- 状态筛选必须在排序与分页之前完成，保证分页结果只包含符合条件的任务。

### REQ-001  (specs/taskboard.md)
## REQ-001 列表排序

`list_tasks` 返回的任务必须按 `due_date` 升序排列；`due_date` 相同时按 `id` 升序排列。

### REQ-002  (specs/taskboard.md)
## REQ-002 分页

`list_tasks` 支持 `limit` 与 `offset` 参数：先完成排序，再进行分页切分，最后返回当前页。

### REQ-004  (specs/taskboard.md)
## REQ-004 输入校验

- `limit` 必须是正整数，否则抛出 `ValueError`。
- `offset` 必须大于等于 0，否则抛出 `ValueError`。

## 相关代码
### src/taskboard/service.py#L6 list_tasks
```python
def list_tasks(
    tasks: Iterable[Task],
    limit: int = 10,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Task]:
    """Return a sorted, paginated page of tasks.

    REQ-001: sort by (due_date, id) ascending.
    REQ-002: sort first, then paginate with limit/offset.
    REQ-003: filter by status before sorting/pagination (not implemented yet).
    REQ-004: validate limit/offset and raise ValueError on invalid input.
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    ordered = sorted(tasks, key=lambda task: (task.due_date, task.id))

    # TODO(REQ-003): apply the status filter here, before pagination.

    return ordered[offset : offset + limit]
```

### src/taskboard/models.py#L4 Task
```python
@dataclass(frozen=True)
class Task:
    id: int
    title: str
    status: str
    due_date: str
```

## 相关测试
### tests/test_regression.py::test_no_status_returns_all
```python
def test_no_status_returns_all():
    result = list_tasks(make_tasks(), limit=10, offset=0, status=None)
    assert len(result) == 5
```

### tests/test_target_filter.py::test_filter_active_only
```python
def test_filter_active_only():
    result = list_tasks(make_tasks(), status="active")
    assert [t.id for t in result] == [1, 3, 5]
```

### tests/test_target_filter.py::test_filter_then_sort_and_paginate
```python
def test_filter_then_sort_and_paginate():
    result = list_tasks(make_tasks(), status="active", limit=2, offset=0)
    assert [t.id for t in result] == [1, 3]
```

### tests/test_regression.py::test_sorts_by_due_date_then_id
```python
def test_sorts_by_due_date_then_id():
    result = list_tasks(make_tasks())
    assert [t.id for t in result] == [1, 2, 3, 4, 5]
```

### tests/test_regression.py::test_pagination_after_sorting
```python
def test_pagination_after_sorting():
    result = list_tasks(make_tasks(), limit=2, offset=1)
    assert [t.id for t in result] == [2, 3]
```

### tests/test_regression.py::test_invalid_limit_raises
```python
def test_invalid_limit_raises():
    with pytest.raises(ValueError):
        list_tasks(make_tasks(), limit=0)
```
