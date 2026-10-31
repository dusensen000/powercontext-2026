from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    status: str
    due_date: str
