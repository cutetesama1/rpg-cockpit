"""Opt-in live wardrobe extraction probes. No user saves/packs/settings are written."""
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for part in ("core","gateway","content"): sys.path.insert(0,str(ROOT/part))
from rpg_content import load_pack
from rpg_core.contracts import LlmProfile, LlmRolesConfig, NarratorOutput, OpeningScene
from rpg_core.runtime import GameSession
from rpg_gateway import LlmResponse, LlmRouter
from rpg_gateway.factory import build_providers
from rpg_gateway.settings import load_settings

class FixedNarrator:
    name="fixture"
    text=""
    def complete(self,request):
        return LlmResponse(narrator=NarratorOutput(narrative=self.text),model="fixed-narrative-fixture",provider=self.name)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true",required=True)
    parser.add_argument("--full-only",action="store_true")
    args=parser.parse_args()
    settings=load_settings().model_copy(deep=True)
    profile=settings.roles.narrator.model_copy(deep=True)
    cfg=settings.providers.get(profile.provider)
    if not cfg or not cfg.api_key: raise SystemExit("No authenticated provider configured; no calls made.")
    cfg.timeout=45; cfg.max_retries=0; profile.max_tokens=2048; profile.temperature=0
    providers=build_providers(settings)
    fixed=FixedNarrator(); providers[fixed.name]=fixed
    roles=LlmRolesConfig(separated=True,narrator=LlmProfile(provider=fixed.name),settler=profile)
    def pack():
        content=load_pack(ROOT/"packs/new-game")
        content.prompts={"pre":"普通冒险测试，场景为训练室、更衣室与休息室。", "narrator":"只叙述指定事件，不添加额外的数值、奖励或动作。", "settler":"状态变化必须通过工具，避免额外事件。"}
        content.prompt_versions={};content.worldbook=[];content.npcs=[];content.items=[];content.skills=[];content.quests=[]
        content.opening=OpeningScene(id="opening",text="你站在训练室的更衣柜前，旁边是衣架和练习木桩。")
        content.scenes=[content.opening]
        return content
    session=GameSession(pack(),LlmRouter(roles,providers))
    secrets=[p.api_key for p in settings.providers.values() if p.api_key]
    def safe(text):
        for secret in secrets:text=text.replace(secret,"[redacted]")
        return re.sub(r"https?://[^\s]+","[endpoint]",text)
    output=ROOT/"docs/previews/p14-live-clothing-verification.json"
    records=json.loads(output.read_text(encoding="utf-8"))["scenarios"][:6] if args.full_only else []
    def run(label,text,expected,game=session,fixture=True):
        if fixture and args.full_only: return
        if fixture:fixed.text=text
        before=dict(game.state)
        result=game.submit_action({"kind":"text","text":"继续这一场普通训练。" if fixture else text})
        subset=lambda state:{k:state[k] for k in ("upper","lower","upper_condition","lower_condition","hp","focus")}
        entry={"scenario":label,"narrative_source":"fixed_fixture" if fixture else "live_narrator", "settler_source":"live_authenticated_provider",
               "ok":result.ok,"expectation_met":bool(result.ok and expected(game.state)),
               "before":subset(before),"after":subset(game.state),"narrative":safe(result.narrative),
               "applied_clothing":[e["payload"] for e in result.events if e["kind"]=="tool.applied" and e["payload"].get("tool")=="update_clothing"],
               "errors":[safe(e) for e in result.errors],"replay_equal":game.verify()["equal"],
               "calls":[{"role":e["role"],"model":e["payload"].get("model"),"tokens":e["payload"].get("usage",{}).get("total_tokens",0)} for e in result.events if e["kind"]=="llm.usage"]}
        records.append(entry)
        output=ROOT/"docs/previews/p14-live-clothing-verification.json"
        output.parent.mkdir(parents=True,exist_ok=True)
        report={"tested_at":datetime.now(timezone.utc).isoformat(),"provider":profile.provider,"model":profile.model or cfg.model,"isolated_in_memory":True,"user_settings_unchanged":True,"scenarios":records}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({k:entry[k] for k in ("scenario","ok","expectation_met","after")},ensure_ascii=False),flush=True)
    run("scene_actual_change","你进入训练室，在更衣柜前换上连帽卫衣和长裤，把原来的T恤和牛仔裤放进柜里。",lambda s:s["upper"]=="hoodie" and s["lower"]=="trousers")
    run("damage","你穿过荆棘，卫衣的袖子被勾破，留下明显的裂口；长裤没有受损。",lambda s:s["upper"]=="hoodie" and s["upper_condition"]=="damaged" and s["lower_condition"]=="intact")
    run("keep_previous_damage","你在窗边坐下，卫衣仍保持刚才的破损。你翻开书，没有更换衣服，也没有修补。",lambda s:s["upper"]=="hoodie" and s["upper_condition"]=="damaged")
    run("quoted_plan_is_not_change","教练说：“下次训练可以换毛衣。”你只是点头，没有换衣，也没有修补卫衣。",lambda s:s["upper"]=="hoodie" and s["upper_condition"]=="damaged")
    run("repair","你用针线把卫衣袖口的裂缝完全修补好，衣物恢复完好。",lambda s:s["upper"]=="hoodie" and s["upper_condition"]=="intact")
    run("rest_room_change","训练结束，你到休息室脱下卫衣与长裤，换上毛衣和牛仔裤。",lambda s:s["upper"]=="sweater" and s["lower"]=="jeans" and s["upper_condition"]=="intact")
    # This last case uses the real model for both narration and backend extraction.
    shared=LlmRolesConfig(separated=False,narrator=profile,settler=LlmProfile(provider="scripted"))
    live_game=GameSession(pack(),LlmRouter(shared,providers))
    run("live_narrator_to_live_settler","已经确定发生的事件：我在训练室的更衣柜前，把T恤和牛仔裤换成连帽卫衣（hoodie）和长裤（trousers）。请叙述实际换衣完成的结果，不添加损坏、修补或数值变化。",lambda s:s["upper"]=="hoodie" and s["lower"]=="trousers",game=live_game,fixture=False)
    print(json.dumps({"scenarios":len(records),"passed":sum(r["expectation_met"] for r in records),"replay_equal":all(r["replay_equal"] for r in records)},ensure_ascii=False))
    if not all(r["expectation_met"] for r in records):raise SystemExit(1)

if __name__=="__main__":main()
