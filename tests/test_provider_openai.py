"""OpenAI 兼容 provider：本地假端点验证 tool_calls / content 解析 / 错误处理。

不依赖外网、不依赖真实 API Key：用一个线程里的 http.server 回放固定响应。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import PACK_DIR  # noqa: F401  （注入 sys.path）

from rpg_content import load_pack
from rpg_core.contracts import (
    LlmProfile,
    LlmRolesConfig,
    LlmSettings,
    ProviderSettings,
)
from rpg_core.runtime import GameSession
from rpg_gateway import (
    LlmResponse,
    OpenAICompatibleProvider,
    build_router,
    parse_narrator_content,
)


class _Handler(BaseHTTPRequestHandler):
    queue: list[dict] = []
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        payload = dict(type(self).queue.pop(0)) if type(self).queue else {}
        status = int(payload.pop("__status__", 200))
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:  # 静音
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Handler.queue = []
    _Handler.received = []
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, _Handler
    httpd.shutdown()


def _tool_call_response(name: str = "damage", args: str = '{"amount": 5, "reason": "测试"}') -> dict:
    return {
        "model": "fake-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": name, "arguments": args},
                        }
                    ],
                }
            }
        ],
    }


def _narrative_response(usage: dict | None = None) -> dict:
    content = json.dumps(
        {
            "narrative": "影子退进暗处，冷柜的嗡鸣盖过了你的呼吸。",
            "options": [
                {"id": "o1", "label": "继续", "action_text": "你跟上去"},
                {"id": "o2", "label": "查看", "action_text": "你低头查看"},
            ],
        },
        ensure_ascii=False,
    )
    payload = {
        "model": "fake-model",
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def test_tool_calls_are_parsed(server):
    base, handler = server
    handler.queue = [_tool_call_response()]
    provider = OpenAICompatibleProvider(base_url=base + "/v1", api_key="sk-test", model="fake-model")
    response = provider.complete({"system_prompt": "测试", "action": {"kind": "text"}})

    assert response.model == "fake-model"
    assert response.tool_calls[0].name == "damage"
    assert response.tool_calls[0].args["amount"] == 5

    sent = handler.received[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert len(sent["body"]["tools"]) == 9
    assert sent["body"]["model"] == "fake-model"


def test_content_json_is_parsed_to_narrator(server):
    base, handler = server
    handler.queue = [_narrative_response()]
    provider = OpenAICompatibleProvider(base_url=base + "/v1", model="fake-model")
    response = provider.complete({"system_prompt": "测试", "action": {"kind": "text"}})

    assert response.narrator is not None
    assert "影子" in response.narrator.narrative
    assert response.narrator.options[0].action_text == "你跟上去"


def test_http_error_becomes_runtime_error(server):
    base, handler = server
    # 默认 max_retries=2：500 会重试两次再失败
    handler.queue = [{"__status__": 500, "error": {"message": "boom"}}] * 3
    provider = OpenAICompatibleProvider(
        base_url=base, model="fake-model", retry_backoff_ms=1
    )
    with pytest.raises(RuntimeError, match="HTTP 500") as excinfo:
        provider.complete({"system_prompt": "测试"})
    assert "已重试 2 次" in str(excinfo.value)


def test_retry_then_success_reports_attempts(server):
    base, handler = server
    handler.queue = [{"__status__": 503}, _narrative_response()]
    provider = OpenAICompatibleProvider(
        base_url=base, model="fake-model", max_retries=1, retry_backoff_ms=1
    )
    response = provider.complete({"system_prompt": "测试"})
    assert response.narrator is not None
    assert response.attempts == 2
    assert len(handler.received) == 2


def test_client_error_is_not_retried(server):
    base, handler = server
    handler.queue = [{"__status__": 401, "error": {"message": "bad key"}}]
    provider = OpenAICompatibleProvider(
        base_url=base, model="fake-model", max_retries=2, retry_backoff_ms=1
    )
    with pytest.raises(RuntimeError, match="HTTP 401"):
        provider.complete({"system_prompt": "测试"})
    assert len(handler.received) == 1


def test_usage_and_cost_are_recorded(server):
    base, handler = server
    handler.queue = [
        _narrative_response(
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        )
    ]
    provider = OpenAICompatibleProvider(
        base_url=base,
        model="fake-model",
        price_in=2.0,
        price_out=8.0,
        retry_backoff_ms=1,
    )
    response = provider.complete({"system_prompt": "测试"})
    assert response.usage["total_tokens"] == 150
    # 100/1M*2 + 50/1M*8 = 0.0002 + 0.0004
    assert response.cost_usd == pytest.approx(0.0006)


def test_missing_endpoint_is_rejected():
    provider = OpenAICompatibleProvider(base_url="", model="fake-model")
    with pytest.raises(RuntimeError, match="base_url"):
        provider.complete({"system_prompt": "测试"})


def test_parse_narrator_content_variants():
    fenced = '```json\n{"narrative": "风停了", "options": ["点烟"]}\n```'
    out = parse_narrator_content(fenced)
    assert out.narrative == "风停了"
    assert out.options[0].label == "点烟"

    plain = parse_narrator_content("只是一段普通叙述。")
    assert plain.narrative == "只是一段普通叙述。"
    assert plain.options == []


def test_parse_narrator_content_accepts_chinese_keys():
    """真实模型会自己把键名译成中文：叙述 / 选项 也要能解析，不能整段 JSON 当叙述。"""
    raw = (
        '{"叙述": "走廊里已经站着一个人。", "选项": ['
        '{"id": "opt_1", "标签": "反问", "行动文本": "我没有回答他。"},'
        '{"id": "opt_2", "label": "后退", "action_text": "我往后退了半步。"}]}'
    )
    out = parse_narrator_content(raw)
    assert out.narrative == "走廊里已经站着一个人。"
    assert [item.label for item in out.options] == ["反问", "后退"]
    assert out.options[0].action_text == "我没有回答他。"


def test_router_with_real_provider_end_to_end(server):
    from rpg_core.settlement import DOMAINS
    base,handler=server
    narrative=_narrative_response()
    text=json.loads(narrative['choices'][0]['message']['content'])['narrative']
    batch={'checked':list(DOMAINS),'operations':[{'name':'damage','args':{'amount':4},'evidence':text}]}
    handler.queue=[narrative,_tool_call_response('settle_turn',json.dumps(batch,ensure_ascii=False))]
    settings=LlmSettings(roles=LlmRolesConfig(narrator=LlmProfile(provider='openai')),providers={'openai':ProviderSettings(base_url=base+'/v1',model='fake-model')})
    game=GameSession(load_pack(PACK_DIR),build_router(settings));result=game.submit_action({'kind':'text','text':'行动'})
    assert result.ok and result.state['hp']==16 and game.verify()['equal']
    first,second=[x['body'] for x in handler.received]
    assert 'tools' not in first and len(second['messages'])==2
    assert [t['function']['name'] for t in second['tools']]==['settle_turn']
    assert not any(m['role'] in ('assistant','tool') for m in second['messages'])
    assert game.usage_status()['calls']==2


def test_reasoning_effort_sent_only_when_selected(server):
    """思考强度：选「自动」不带参数；选 low/medium/high 才透传。"""
    base, handler = server
    handler.queue = [_narrative_response(), _narrative_response()]

    plain = OpenAICompatibleProvider(base_url=base + "/v1", model="gpt-4o")
    plain.complete({"system_prompt": "测试", "action": {"kind": "text"}})
    assert "reasoning_effort" not in handler.received[0]["body"]

    reasoning = OpenAICompatibleProvider(
        base_url=base + "/v1", model="o3", reasoning_effort="high"
    )
    reasoning.complete({"system_prompt": "测试", "action": {"kind": "text"}})
    assert handler.received[1]["body"]["reasoning_effort"] == "high"


def test_input_mode_and_extras_are_rendered():
    """输入模式与附加请求会以人话写进 user 消息，方便任何内容包复用。"""
    messages = OpenAICompatibleProvider._messages(
        {
            "system_prompt": "测试",
            "action": {
                "kind": "text",
                "text": "推门进去",
                "mode": "action",
                "extras": ["inspect", "task"],
            },
        }
    )
    user_text = next(m["content"] for m in messages if m["role"] == "user")
    assert "# 玩家本回合输入模式" in user_text
    assert "玩家实际执行的行为" in user_text
    assert "# 玩家本回合附加请求" in user_text
    assert "审视：" in user_text
    assert "任务：" in user_text
    # 未标注模式/没有附加请求时不出现这两段
    plain = OpenAICompatibleProvider._messages(
        {"system_prompt": "测试", "action": {"kind": "text", "text": "推门"}}
    )
    plain_user = next(m["content"] for m in plain if m["role"] == "user")
    assert "# 玩家本回合输入模式" not in plain_user
    assert "# 玩家本回合附加请求" not in plain_user


def test_router_passes_preset_model_and_effort_to_provider():
    settings = LlmSettings(
        roles=LlmRolesConfig(
            narrator=LlmProfile(provider="deepseek"),
            settler=LlmProfile(provider="deepseek"),
        ),
        providers={
            "deepseek": ProviderSettings(
                base_url="https://api.deepseek.com/v1",
                model="deepseek-reasoner",
                preset="deepseek",
                reasoning_effort="medium",
            )
        },
    )
    router = build_router(settings)
    provider = router.providers["deepseek"]
    assert provider.preset == "deepseek"
    assert provider.reasoning_effort == "medium"
    assert provider.model == "deepseek-reasoner"


def test_messages_render_segments_and_picked_skills():
    """分段标注与勾选技能以自然语言注入，并明确消耗已由框架扣除。"""
    from rpg_gateway.providers import OpenAICompatibleProvider

    request = {
        "system_prompt": "系统提示词",
        "state_brief": "hp 20",
        "scene_brief": "便利店门口",
        "action": {
            "kind": "text",
            "text": "推开门喊「有人吗」，心里有点发毛",
            "segments": [
                {"mode": "action", "text": "推开门"},
                {"mode": "speech", "text": "有人吗"},
                {"mode": "thought", "text": "心里有点发毛"},
            ],
            "skills": [
                {"skill_id": "smash", "name": "撬棍击打"},
                {"skill_id": "first_aid", "name": "急救包扎"},
            ],
        },
    }
    user = OpenAICompatibleProvider._messages(request)[1]["content"]

    assert "# 玩家本回合输入（一段话里可能混有多种类型" in user
    assert "1. [动作（实际执行的行为）] 推开门" in user
    assert "2. [话语（说出口的话）] 有人吗" in user
    assert "3. [心理（只在心里想）] 心里有点发毛" in user
    assert "# 玩家本回合勾选的技能（消耗与冷却已由框架扣除" in user
    assert "- 撬棍击打（smash）" in user
    assert "- 急救包扎（first_aid）" in user
    assert "不要新增数值结算" in user


def test_messages_render_opening_without_player_action():
    """开局请求：不再渲染「玩家本回合行动」，改为明确的开场写作指令。"""
    from rpg_gateway.providers import OpenAICompatibleProvider

    request = {
        "system_prompt": "系统提示词",
        "opening": True,
        "allow_tools": False,
        "action": {"kind": "text", "text": ""},
    }
    user = OpenAICompatibleProvider._messages(request)[1]["content"]

    assert "# 这是新游戏的开场" in user
    assert "不要替玩家行动、说话或做决定" in user
    assert "# 玩家本回合行动" not in user

    normal = OpenAICompatibleProvider._messages(
        {"system_prompt": "系统提示词", "action": {"kind": "text", "text": "推门"}}
    )[1]["content"]
    assert "# 玩家本回合行动" in normal
    assert "# 这是新游戏的开场" not in normal


def test_payload_omits_max_tokens_when_unlimited():
    """max_tokens 为 0 = 不限制：请求体里根本不出现这个键，避免长叙事被截断。"""
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:9", model="fake")

    unlimited = provider._payload({"system_prompt": "提示", "max_tokens": 0})
    assert "max_tokens" not in unlimited
    assert provider._payload({"system_prompt": "提示"}).get("max_tokens") is None

    limited = provider._payload({"system_prompt": "提示", "max_tokens": 4096})
    assert limited["max_tokens"] == 4096


def test_payload_exposes_learn_skill_tool():
    """learn_skill 必须作为工具暴露给模型，否则 AI 无法在游戏里给玩家加技能。"""
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:9", model="fake")
    payload = provider._payload({"system_prompt": "提示", "allow_tools": True})
    names = [tool["function"]["name"] for tool in payload["tools"]]
    assert "learn_skill" in names

    opening = provider._payload(
        {"system_prompt": "提示", "allow_tools": False}
    )
    assert "tools" not in opening


def test_router_passes_omitted_max_tokens_and_temperature():
    """路由把 profile 的 temperature 透传；max_tokens<=0 时不塞进请求。"""
    session = GameSession(
        load_pack(PACK_DIR),
        _router_with_max_tokens(0),
    )
    provider = session.router.providers["stub"]
    assert session.submit_action({"kind": "text", "text": "看看四周"}).ok is True
    assert "max_tokens" not in provider.requests[0]
    assert provider.requests[0]["temperature"] == 0.7

    limited_provider = _StubProvider([_say("你又看了一眼货架。")])
    router = _router_with_max_tokens(8192, provider=limited_provider)
    session = GameSession(load_pack(PACK_DIR), router)
    assert session.submit_action({"kind": "text", "text": "再看看"}).ok is True
    assert limited_provider.requests[0]["max_tokens"] == 8192


from conftest import StubProvider as _StubProvider


def _say(text: str):
    from rpg_core.contracts import NarratorOutput, Option

    return LlmResponse(
        narrator=NarratorOutput(
            narrative=text, options=[Option(id="o1", label="继续", action_text="继续")]
        )
    )


def _router_with_max_tokens(max_tokens: int, provider=None):
    from rpg_gateway import LlmRouter

    provider = provider or _StubProvider([_say("你环顾四周。")])
    profile = LlmProfile(provider="stub", max_tokens=max_tokens)
    config = LlmRolesConfig(
        separated=False,
        narrator=profile,
        settler=profile,
        arbiter=profile,
        setup=profile,
    )
    return LlmRouter(config, {"stub": provider})


def test_parse_narrator_content_reads_status_with_chinese_keys():
    raw = json.dumps(
        {
            "叙述": "光从门缝里渗出来。",
            "选项": [{"标签": "推门", "行动文本": "我推开门。"}],
            "状态": {
                "姓名": "露娜莉亚",
                "色情程度": 120,
                "小穴与身体": 30,
                "敏感度": "45",
                "倾向": -5,
            },
        },
        ensure_ascii=False,
    )

    out = parse_narrator_content(raw)

    assert out.status is not None
    assert out.status.name == "露娜莉亚"
    assert out.status.lewd == 100
    assert out.status.body == 30
    assert out.status.sensitivity == 45
    assert out.status.desire == 0


def test_parse_narrator_content_status_is_optional():
    out = parse_narrator_content(json.dumps({"narrative": "只有叙事。"}))

    assert out.narrative == "只有叙事。"
    assert out.status is None


def test_messages_keep_state_out_of_narration():
    messages=OpenAICompatibleProvider._messages({'phase':'narration','allow_tools':False,'system_prompt':'只负责叙事','action':{'text':'观察'}})
    user=messages[1]['content']
    assert '禁止调用状态工具或输出 status' in user


def test_skill_payments_are_rendered_for_model():
    """技能扣费汇总会写进提示词：告诉模型这些已经扣过，别再扣一遍。"""
    messages = OpenAICompatibleProvider._messages(
        {
            "system_prompt": "测试",
            "action": {"kind": "text", "text": "挥棍砸门"},
            "payments": [
                {"field": "stamina", "label": "体力", "amount": 3, "remaining": 7}
            ],
        }
    )
    user_text = next(m["content"] for m in messages if m["role"] == "user")
    assert "# 本回合技能扣费已经由框架结算（不要重复扣）" in user_text
    assert "- 体力（stamina）：本回合已扣 3，现在剩 7" in user_text
    assert "技能本身的代价在叙事里用文字描写就行" in user_text

    plain = OpenAICompatibleProvider._messages(
        {"system_prompt": "测试", "action": {"kind": "text", "text": "走两步"}}
    )
    plain_user = next(m["content"] for m in plain if m["role"] == "user")
    assert "# 本回合技能扣费已经由框架结算" not in plain_user


def test_parse_narrator_content_reads_status_notes():
    """status 的 notes（或每项写成 {score,note}）会被读成四项短描述。"""
    content = json.dumps(
        {
            "narrative": "你把手收回来。",
            "options": [],
            "status": {
                "name": "露娜",
                "lewd": 3,
                "小穴与身体": "干燥、无异状，未受刺激",
                "sensitivity": 18,
                "desire": 12,
                "notes": {"lewd": "只是有点好奇", "敏感度": "被碰到会绷紧"},
            },
        },
        ensure_ascii=False,
    )
    out = parse_narrator_content(content)
    assert out.status is not None
    assert out.status.lewd == 3
    assert out.status.notes["body"] == "干燥、无异状，未受刺激"
    assert out.status.notes["lewd"] == "只是有点好奇"
    assert out.status.notes["sensitivity"] == "被碰到会绷紧"

    nested = parse_narrator_content(
        json.dumps(
            {
                "narrative": "她缩了一下。",
                "status": {
                    "name": "露娜",
                    "body": {"score": 5, "note": "微微泛红"},
                },
            },
            ensure_ascii=False,
        )
    )
    assert nested.status is not None
    assert nested.status.body == 5
    assert nested.status.notes["body"] == "微微泛红"


def test_post_narrative_clothing_uses_separate_request_and_only_wardrobe_tool(server):
    from pathlib import Path
    base, handler = server
    text = "你在训练室换上卫衣。"
    narrative = {"choices": [{"message": {"content": json.dumps({"narrative": text, "options": []}, ensure_ascii=False)}}]}
    from rpg_core.settlement import DOMAINS
    batch={"checked":list(DOMAINS),"operations":[{"name":"update_clothing","args":{"changes":[{"slot":"upper","garment":"hoodie","evidence":text}]},"evidence":text}]}
    handler.queue = [narrative, _tool_call_response("settle_turn", json.dumps(batch,ensure_ascii=False))]
    provider = OpenAICompatibleProvider(base_url=base, model="fake-model")
    profile = LlmProfile(provider="fake", model="fake-model")
    router = build_router(LlmSettings(roles=LlmRolesConfig(narrator=profile), providers={"fake": ProviderSettings(base_url=base, model="fake-model")}))
    game = GameSession(load_pack(Path(__file__).resolve().parents[1] / "packs/new-game"), router)
    result = game.submit_action({"kind": "text", "text": "换衣"})
    assert result.ok and result.state["upper"] == "hoodie"
    assert len(handler.received) == 2
    backend = handler.received[1]["body"]
    assert backend["tool_choice"] == "auto"
    data = json.loads(backend["messages"][1]["content"])
    assert data["narrative"] == text and "state" in data and "wardrobe" in data
    assert not {"recent","events","tool_exchanges"} & data.keys()


def test_mobile_checkbox_modes_are_distinguished_without_executing_thoughts():
    request={"action":{"kind":"text","text":"我向前走，并想着明天再来。","modes":["action","thought","action","unknown"]}}
    user=OpenAICompatibleProvider._messages(request)[1]["content"]
    assert "# 玩家本回合勾选的输入类型" in user
    assert "这是玩家实际执行的行为" in user
    assert "内心活动" in user
    assert "没有执行" in user
    assert "不是说出口的话" in user
    assert "不要把同一句内容重复写成多种类型" in user


def test_mobile_segments_remain_more_precise_than_checkbox_modes():
    request={"action":{"kind":"text","text":"你好","modes":["action","thought"],"segments":[{"mode":"speech","text":"你好"}]}}
    user=OpenAICompatibleProvider._messages(request)[1]["content"]
    assert "按每段标注分别处理" in user
    assert "# 玩家本回合勾选的输入类型" not in user



def test_preset_phases_have_readonly_selection_and_exact_learning_tool():
    provider = OpenAICompatibleProvider(base_url="http://unused", model="test")
    selection = provider._payload({"phase":"skill_selection","allow_tools":False,"world":"你是强大的法师","candidates":[]})
    assert "tools" not in selection
    assert "强大法师" in selection["messages"][0]["content"]
    learning = provider._payload({"phase":"skill_learning","narrative":"你学会了火弹。","catalog_candidates":[]})
    assert [tool["function"]["name"] for tool in learning["tools"]] == ["learn_catalog_skills"]
    ordinary = provider._payload({"catalog_mode":True,"catalog_candidates":[]})
    assert "learn_skill" not in {tool["function"]["name"] for tool in ordinary["tools"]}
    assert "learn_catalog_skills" not in {tool["function"]["name"] for tool in ordinary["tools"]}
