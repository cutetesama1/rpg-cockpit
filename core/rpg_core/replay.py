"""回放与一致性校验：replay == live。"""
from __future__ import annotations

from .contracts import Event, StateSchema
from .state import project


def replay(events: list[Event], schema: StateSchema) -> dict:
    return project(events, schema)


def verify(live_state: dict, events: list[Event], schema: StateSchema) -> dict:
    replayed = replay(events, schema)
    return {
        "equal": replayed == live_state,
        "live": live_state,
        "replay": replayed,
        "diff": {
            k: {"live": live_state.get(k), "replay": replayed.get(k)}
            for k in sorted(set(live_state) | set(replayed))
            if live_state.get(k) != replayed.get(k)
        },
    }
