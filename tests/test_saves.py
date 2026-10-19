"""P4 存档：多槽位、读档续玩、事件流校验、日志脱敏。"""
from __future__ import annotations

import json

import pytest
from conftest import PACK_DIR, make_session

from rpg_content import load_pack
from rpg_core.saves import (
    AUTO_SLOT,
    delete_save,
    export_log,
    list_saves,
    normalize_slot,
    read_save,
    redact,
    restore_session,
    save_session,
    saves_dir,
)
from rpg_gateway import LlmRouter, ScriptedProvider

from conftest import roles


def _session():
    from rpg_core.runtime import GameSession

    return GameSession(load_pack(PACK_DIR), LlmRouter(roles("scripted"), {"scripted": ScriptedProvider()}))


@pytest.fixture()
def save_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_SAVES", str(tmp_path / "saves"))
    return tmp_path / "saves"


def test_save_reports_summary_and_file(save_dir):
    session = _session()
    assert session.submit_action({"kind": "skill", "skill_id": "observe"}).ok is True

    summary = save_session(session, slot="night-1", label="第一次进店")
    assert summary["slot"] == "night-1"
    assert summary["label"] == "第一次进店"
    assert summary["turn"] == 1
    assert summary["state"] == session.state
    assert (save_dir / "night-1.json").is_file()

    payload = read_save("night-1")
    assert payload["save_version"] == 1
    assert len(payload["events"]) == len(session.ledger.events)


def test_list_saves_sorted_and_filtered(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    save_session(session, slot="a", label="A")
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    save_session(session, slot="b", label="B")

    listing = list_saves()
    assert listing["dir"] == str(save_dir)
    assert [row["slot"] for row in listing["saves"]] == ["b", "a"]
    assert listing["saves"][0]["label"] == "B"

    assert list_saves(pack_id="not-this-pack")["saves"] == []


def test_restore_session_resumes_turn_state_and_scene(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "smash"})
    session.submit_action({"kind": "option", "option_id": "opt_enter"})
    saved_turn, saved_state = session.turn, dict(session.state)
    save_session(session, slot="midway")

    fresh = _session()
    assert fresh.turn == 0
    summary = restore_session(fresh, read_save("midway"))
    assert summary["turn"] == saved_turn
    assert fresh.turn == saved_turn
    assert fresh.state == saved_state
    assert fresh.scene_id == "aisle"
    assert fresh.verify()["equal"] is True


def test_restored_session_can_continue_playing(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    save_session(session, slot="before")

    fresh = _session()
    restore_session(fresh, read_save("before"))
    result = fresh.submit_action({"kind": "skill", "skill_id": "observe"})
    assert result.ok is True
    assert fresh.turn == 2
    assert fresh.verify()["equal"] is True


def test_restore_rejects_other_pack(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    save_session(session, slot="x")
    payload = read_save("x")
    payload["pack_id"] = "another-game"

    with pytest.raises(ValueError, match="当前游戏"):
        restore_session(_session(), payload)


def test_restore_rejects_tampered_state(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    save_session(session, slot="x")
    payload = read_save("x")
    payload["state"] = dict(payload["state"], hp=1)

    with pytest.raises(ValueError, match="不一致"):
        restore_session(_session(), payload)


def test_delete_save_and_missing(save_dir):
    session = _session()
    save_session(session, slot="gone")
    assert delete_save("gone") is True
    assert delete_save("gone") is False
    with pytest.raises(FileNotFoundError):
        read_save("gone")


def test_corrupt_save_listed_as_broken(save_dir):
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "bad.json").write_text("{not json", encoding="utf-8")
    listing = list_saves()
    assert listing["saves"] == []
    assert listing["broken"][0]["slot"] == "bad"


def test_slot_name_validation(save_dir):
    assert normalize_slot(" Night 1 ") == "night-1"
    assert normalize_slot(AUTO_SLOT) == "auto"
    for bad in ("", "  ", "../escape", "Upper!", "a" * 80):
        with pytest.raises(ValueError):
            normalize_slot(bad)


def test_auto_save_slot_roundtrip(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    summary = save_session(session, slot=AUTO_SLOT, auto=True)
    assert summary["auto"] is True
    assert (save_dir / "auto.json").is_file()
    assert list_saves()["saves"][0]["slot"] == AUTO_SLOT


def test_export_log_masks_secrets(save_dir):
    session = _session()
    session.submit_action({"kind": "skill", "skill_id": "observe"})
    view = {
        "providers": {
            "openai": {"base_url": "https://api.example.com", "api_key": "sk-secret-abcdef123456"}
        }
    }
    log = export_log(session, settings_view=view, saves=list_saves())
    assert log["pack"]["id"] == "night-convenience-store"
    assert log["turn"] == 1
    text = json.dumps(log, ensure_ascii=False)
    assert "sk-secret-abcdef123456" not in text
    assert "sk-***" in text
    assert log["events"]


def test_redact_text_patterns():
    assert redact("key=sk-abcdefgh12345") == "key=sk-***"
    assert "***" in redact("Authorization: Bearer abc.def.ghi")
    assert redact({"nested": ["sk-zzzzzzzzzzzz"]})["nested"][0] == "sk-***"


def test_saves_dir_env(save_dir):
    assert saves_dir() == save_dir
    session = _session()
    save_session(session, slot="env")
    assert (save_dir / "env.json").is_file()
