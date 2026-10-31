"""Regression tests: these must pass both before and after the target change."""

import pytest

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


def test_sorts_by_due_date_then_id():
    result = list_tasks(make_tasks())
    assert [t.id for t in result] == [1, 2, 3, 4, 5]


def test_pagination_after_sorting():
    result = list_tasks(make_tasks(), limit=2, offset=1)
    assert [t.id for t in result] == [2, 3]


def test_no_status_returns_all():
    result = list_tasks(make_tasks(), limit=10, offset=0, status=None)
    assert len(result) == 5


def test_invalid_limit_raises():
    with pytest.raises(ValueError):
        list_tasks(make_tasks(), limit=0)


def test_invalid_offset_raises():
    with pytest.raises(ValueError):
        list_tasks(make_tasks(), offset=-1)
