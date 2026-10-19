"""True streamed HTTP, public-text extraction and transactional preview regression."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import PACK_DIR, roles
from rpg_content import load_pack
from rpg_core.runtime import GameSession
from rpg_gateway import LlmRouter, OpenAICompatibleProvider
from rpg_gateway.providers import RecordingProvider
from rpg_gateway.streaming import partial_narrative


@pytest.mark.parametrize("key", ["narrative", "text", "叙述", "正文"])
@pytest.mark.parametrize("escaped", [False, True])
def test_partial_json_never_leaks_other_fields_and_decodes_split_escapes(key, escaped):
    expected = '风吹过。\n“你好。” 🌙 \\ 远处'
    raw = json.dumps({"options": [{"narrative": "隐藏选项"}], key: expected, "status": {"name": "隐藏状态"}}, ensure_ascii=escaped)
    snapshots = [partial_narrative(raw[:i]) for i in range(1, len(raw) + 1)]
    assert all(expected.startswith(item) for item in snapshots)
    assert snapshots[-1] == expected
    assert any(0 < len(item) < len(expected) for item in snapshots)
    assert not any("隐藏" in item or "options" in item for item in snapshots)


def test_plain_and_fenced_content():
    assert partial_narrative("普通正文") == "普通正文"
    assert partial_narrative('```json\n{"narrative":"你好') == "你好"
    assert partial_narrative('```j') == ""


class Handler(BaseHTTPRequestHandler):
    scenarios: list[dict] = []
    received: list[dict] = []
    finished = False
    observed = threading.Event()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        type(self).received.append(body)
        scenario = type(self).scenarios.pop(0)
        self.send_response(scenario.get("status", 200))
        self.send_header("Content-Type", scenario.get("type", "text/event-stream"))
        self.end_headers()
        if "json" in scenario:
            self.wfile.write(json.dumps(scenario["json"]).encode())
            return
        for index, packet in enumerate(scenario["packets"]):
            encoded = ("data: " + (packet if isinstance(packet, str) else json.dumps(packet, ensure_ascii=False)) + "\r\n\r\n").encode("utf-8")
            # Split inside UTF-8 and SSE boundaries as a real HTTP server may do.
            for part in (encoded[:17], encoded[17:]):
                self.wfile.write(part)
                self.wfile.flush()
            if scenario.get("pause") == index:
                type(self).observed.wait(2)
        type(self).finished = True

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    Handler.scenarios = []
    Handler.received = []
    Handler.finished = False
    Handler.observed = threading.Event()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", Handler
    httpd.shutdown()
    httpd.server_close()


def chunk(content=None, *, tools=None, reason=None, reasoning=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if tools is not None:
        delta["tool_calls"] = tools
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return {"model": "stream-test", "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}


def narrative_packets(text="你听见风声。“你好。”"):
    raw = json.dumps({"narrative": text, "options": [{"label": "继续", "action_text": "继续"}]}, ensure_ascii=False)
    parts = [raw[i:i+5] for i in range(0, len(raw), 5)]
    return [chunk(reasoning="不能显示的思考"), *[chunk(part) for part in parts], chunk(reason="stop"),
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}, "[DONE]"]


def provider(base, **kw):
    return OpenAICompatibleProvider(base_url=base, model="stream-test", retry_backoff_ms=0, **kw)


def test_text_arrives_before_http_response_finishes_with_usage_and_recording(server, tmp_path):
    base, handler = server
    handler.scenarios = [{"packets": narrative_packets(), "pause": 4}]
    snapshots = []
    early = []
    def receive(text):
        snapshots.append(text)
        if text:
            early.append(not handler.finished)
            handler.observed.set()
    log = tmp_path / "record.jsonl"
    response = RecordingProvider(provider(base, price_in=2, price_out=8), log).stream({}, receive)
    assert response.narrator.narrative == "你听见风声。“你好。”"
    assert len([text for text in snapshots if text]) > 2
    assert any(early)
    assert response.usage["total_tokens"] == 150
    assert response.cost_usd == .0006
    assert handler.received[0]["stream"] is True
    assert handler.received[0]["stream_options"] == {"include_usage": True}
    assert json.loads(log.read_text(encoding="utf-8"))["response"]["narrator"]["narrative"] == response.narrator.narrative


def test_tool_arguments_are_reassembled_without_becoming_prose(server):
    base, handler = server
    handler.scenarios = [{"packets": [
        chunk(tools=[{"index": 0, "id": "tc1", "function": {"name": "damage", "arguments": '{"amount":'}}]),
        chunk(tools=[{"index": 0, "function": {"arguments": '2,"reason":"撞击"}'}}]),
        chunk(reason="tool_calls"), "[DONE]",
    ]}]
    snapshots = []
    result = provider(base).stream({}, snapshots.append)
    assert result.tool_calls[0].args == {"amount": 2, "reason": "撞击"}
    assert result.tool_calls[0].id == "tc1"
    assert not any(snapshots)


@pytest.mark.parametrize("mode", ["ignored", "unsupported", "options"])
def test_endpoints_without_stream_or_usage_options_remain_compatible(server, mode):
    base, handler = server
    complete = {"choices": [{"message": {"content": '{"narrative":"兼容正文"}'}}]}
    if mode == "ignored":
        handler.scenarios = [{"type": "application/json", "json": complete}]
    elif mode == "unsupported":
        handler.scenarios = [{"status": 400, "type": "application/json", "json": {"error": "stream unsupported"}}, {"type": "application/json", "json": complete}]
    else:
        handler.scenarios = [{"status": 400, "type": "application/json", "json": {"error": "stream_options unsupported"}}, {"packets": narrative_packets("兼容正文")}]
    result = provider(base).stream({}, lambda text: None)
    assert result.narrator.narrative == "兼容正文"
    if mode == "unsupported":
        assert "stream" not in handler.received[-1]
    if mode == "options":
        assert handler.received[-1]["stream"] and "stream_options" not in handler.received[-1]


def test_interrupted_stream_retries_with_snapshot_reset(server):
    base, handler = server
    handler.scenarios = [{"packets": [chunk('{"narrative":"旧片段')]}, {"packets": narrative_packets("新正文")}]
    snapshots = []
    result = provider(base, max_retries=1).stream({}, snapshots.append)
    assert result.attempts == 2
    old = snapshots.index("旧片段")
    assert snapshots[old+1] == ""
    assert result.narrator.narrative == "新正文"


@pytest.mark.parametrize("terminal", ["cut", "length", "bad_json"])
def test_incomplete_stream_rolls_back_and_discards_previews(server, terminal):
    base, handler = server
    packets = [chunk('{"narrative":"尚未完成')]
    if terminal == "length": packets += [chunk(reason="length"), "[DONE]"]
    if terminal == "bad_json": packets += [chunk(reason="stop"), "[DONE]"]
    handler.scenarios = [{"packets": packets}]
    p = provider(base, max_retries=0)
    game = GameSession(load_pack(PACK_DIR), LlmRouter(roles(p.name), {p.name: p}))
    snapshots = []
    game.on_narrative = snapshots.append
    before = dict(game.state)
    result = game.submit_action({"kind": "skill", "skill_id": "observe"})
    assert not result.ok and game.state == before and game.turn == 0
    assert any(update["text"] for update in snapshots)
    assert snapshots[-1]["text"] == ""
    assert not any(event.kind.startswith("narrative.") for event in game.ledger.events)
    assert not any(event.kind == "narrative.delta" for event in game.ledger.events)


def test_runtime_streams_opening_and_turn_without_duplicate_charges(server):
    base, handler = server
    from rpg_core.settlement import DOMAINS
    batch={'choices':[{'message':{'content':json.dumps({'checked':list(DOMAINS),'operations':[]})}}]}
    handler.scenarios = [{"packets": narrative_packets("开局风声")},{"type":"application/json","json":batch}, {"packets": narrative_packets("新的回应")},{"type":"application/json","json":batch}]
    p = provider(base, max_retries=0)
    game = GameSession(load_pack(PACK_DIR), LlmRouter(roles(p.name), {p.name: p}))
    snapshots = []
    game.on_narrative = snapshots.append
    assert game.start_opening()["ok"]
    assert any(update["turn"] == 0 and update["text"] for update in snapshots)
    # Opening is idempotent and does not make another network request.
    assert not game.start_opening()["generated"]
    before = dict(game.state)
    result = game.submit_action({"kind": "skill", "skill_id": "observe"})
    assert result.ok
    assert len(handler.received) == 4
    assert len([event for event in game.ledger.events if event.kind == "skill.used"]) == 1
    assert any(update["phase"] == "settling" for update in snapshots)
    assert len([event for event in game.ledger.events if event.kind == "narrative.generated"]) == 2
    assert result.state["stamina"] == before["stamina"]
