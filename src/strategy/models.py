from dataclasses import dataclass


@dataclass(frozen=True)
class TableState:
    to_call: int
    minimum_raise: int
    stack: int


@dataclass(frozen=True)
class Action:
    kind: str
    amount: int | None = None
