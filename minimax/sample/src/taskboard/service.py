from typing import Iterable, List, Optional

from .models import Task


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
