"""Target tests (REQ-003): must FAIL before the change and PASS after it."""

from taskboard.models import Task
from taskboard.service import list_tasks


def make_tasks():
    return [
        Task(id=1, title="Write report", status="active", due_date="2026-05-01"),
        Task(id=2, title="Review PR", status="done", due_date="2026-05-02"),
        Task(id=3, title="Fix bug", status="active", due_date="2026-05-02"),
        Task(id=4, title="Plan sprint", status="done", due_date="2026-05-03"),
        Task(id=5, title="Deploy", status="active", due_date="2026-05-04"),
    ]


def test_filter_active_only():
    result = list_tasks(make_tasks(), status="active")
    assert [t.id for t in result] == [1, 3, 5]


def test_filter_then_sort_and_paginate():
    result = list_tasks(make_tasks(), status="active", limit=2, offset=0)
    assert [t.id for t in result] == [1, 3]
