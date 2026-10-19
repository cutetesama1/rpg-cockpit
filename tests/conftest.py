"""pytest 公共夹具：路径、内容包、假 LLM。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "packs" / "night-convenience-store"
PROBE_PACK_DIR = ROOT / "packs" / "probe-signal-station"
# 测试不碰用户真实设置；每次 pytest 进程用独立临时目录，避免上一轮的
# settings.json（例如被切到真实 provider）污染本轮测试。
os.environ.setdefault("RPG_CONFIG_DIR", tempfile.mkdtemp(prefix="rpg-test-config-"))
# 测试不碰用户真实存档/自动续玩
os.environ.setdefault("RPG_SAVES", str(ROOT / "build" / "test-saves"))
os.environ.setdefault("RPG_NO_RESUME", "1")
for _sub in ("core", "gateway", "content"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from rpg_content import load_pack  # noqa: E402
from rpg_core.contracts import (  # noqa: E402
    LlmProfile,
    LlmRolesConfig,
    NarratorOutput,
    NarratorStatus,
    Option,
    ToolCall,
)
from rpg_core.runtime import GameSession  # noqa: E402
from rpg_gateway import LlmResponse, LlmRouter  # noqa: E402


def roles(provider: str = "stub", separated: bool = False) -> LlmRolesConfig:
    profile = LlmProfile(provider=provider)
    return LlmRolesConfig(
        separated=separated,
        narrator=profile,
        settler=profile,
        arbiter=profile,
        setup=profile,
    )


def make_session(provider, separated: bool = False) -> GameSession:
    router = LlmRouter(roles(provider.name, separated), {provider.name: provider})
    return GameSession(load_pack(PACK_DIR), router)


class StubProvider:
    """按顺序回放响应；列表只剩最后一项时重复使用它。"""

    name = "stub"

    def __init__(self, responses: list[LlmResponse], name: str = "stub") -> None:
        self.responses = list(responses)
        self.name = name
        self.requests: list[dict] = []

    def complete(self, request: dict) -> LlmResponse:
        """Compile older domain fixtures into the new two-phase wire contract.

        Domain tests retain their operation sequences; strict phase and raw-HTTP
        behavior is tested separately in test_stateless_settlement.py.
        """
        from rpg_core.settlement import DOMAINS
        self.requests.append(request)
        assert self.responses, 'StubProvider 响应已耗尽'
        def take():
            return self.responses.pop(0) if len(self.responses)>1 else self.responses[0]
        phase=request.get('phase')
        if phase=='narration':
            self.pending=[]
            while self.responses[0].tool_calls:
                response=take();self.pending.extend(response.tool_calls)
                if len(self.responses)==1 and self.responses[0] is response:
                    return response  # An explicit narrator-tool violation remains a failure.
            response=take()
            self.status_patch=response.narrator.status.model_dump(mode='json') if response.narrator and response.narrator.status else {}
            return response.model_copy(update={'narrator':response.narrator.model_copy(update={'status':None})}) if response.narrator else response
        if phase=='settlement':
            calls=getattr(self,'pending',[]);self.pending=[]
            if request.get('validation_feedback') and not self.responses[0].tool_calls and hasattr(self,'last_settlement'):
                return self.last_settlement
            if not calls and self.responses[0].tool_calls:
                response=take()
                if response.tool_calls[0].name=='settle_turn':return response
                calls=[*calls,*response.tool_calls]
            ops=[]
            for call in calls:
                source='narrative'
                paid={k:v for skill in request.get('paid_skills',[]) for k,v in skill['cost'].items()}
                key=call.args.get('field',call.args.get('target','hp'))
                amount=call.args.get('amount',-call.args.get('delta',0))
                if key in paid and amount==paid[key] and call.name in ('damage','add_stat'):source='skill_cost'
                ops.append({'name':call.name,'args':call.args,'evidence':request['narrative'][:500],'source':source})
            patch=getattr(self,'status_patch',{});self.status_patch={}
            result=LlmResponse(tool_calls=[ToolCall(id='stub_settlement',name='settle_turn',args={'checked':list(DOMAINS),'operations':ops,'status_patch':patch})])
            self.last_settlement=result
            return result
        return take()



def tool(name: str, id: str = "tc_1", **args) -> LlmResponse:
    return LlmResponse(tool_calls=[ToolCall(id=id, name=name, args=args)])


def say(
    text: str = "你环顾四周，冷柜嗡嗡作响。",
    status: NarratorStatus | None = None,
) -> LlmResponse:
    return LlmResponse(
        narrator=NarratorOutput(
            narrative=text,
            options=[Option(id="o1", label="继续", action_text="继续")],
            status=status,
        )
    )


@pytest.fixture()
def pack():
    return load_pack(PACK_DIR)
