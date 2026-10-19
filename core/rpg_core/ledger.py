"""账本：只追加的事件存储。P0 内存实现（P1 换 SQLite，接口不变）。"""
from __future__ import annotations

from typing import Any

from .contracts import Event


class EventLedger:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self._seq = 0

    def append(
        self,
        *,
        turn: int,
        kind: str,
        actor: str = "system",
        role: str | None = None,
        payload: dict[str, Any] | None = None,
        rolls: list[dict[str, Any]] | None = None,
        caused_by: int | None = None,
        prompt_version: str | None = None,
        model: str | None = None,
    ) -> Event:
        self._seq += 1
        event = Event(
            seq=self._seq,
            turn=turn,
            kind=kind,  # type: ignore[arg-type]
            actor=actor,
            role=role,
            payload=payload or {},
            rolls=rolls or [],
            caused_by=caused_by,
            prompt_version=prompt_version,
            model=model,
        )
        self.events.append(event)
        return event

    def for_turn(self, turn: int) -> list[Event]:
        return [e for e in self.events if e.turn == turn]

    def last_committed_turn(self) -> int:
        committed = {e.turn for e in self.events if e.kind == "turn.committed"}
        cancelled = {e.turn for e in self.events if e.kind == "turn.rolled_back"}
        live = committed - cancelled
        return max(live) if live else 0

    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in self.events]
