"""Ask the backend model to choose library refs, then bind canonical world snapshots."""
from __future__ import annotations
import json,re
from pathlib import Path
from rpg_content import load_pack
from rpg_content.skill_library import SkillLibrary,bind_skill
from .world_builder import extract_json


def world_text(pack) -> str:
    return "\n".join([pack.manifest.title,pack.manifest.description,pack.prompts.get("pre", ""),*[e.content for e in pack.worldbook]])


def setting_tags(text: str) -> set[str]:
    tags=set()
    if re.search(r"无魔法|没有魔法|不存在魔法|禁用魔法|无超自然|没有超自然|no magic",text,re.I):tags.add('no_magic')
    if re.search(r"魔法|法师|咒语|施法|术士|奇幻|修仙|仙术|灵力|magic|wizard",text,re.I) and 'no_magic' not in tags:tags.add('magic')
    if re.search(r"空间|传送|瞬移|位面|spatial|teleport",text,re.I):tags.add('spatial_magic')
    for tag,pattern in [('modern',r'现代|都市|modern'),('historical',r'古代|历史|中世纪|historical'),('wuxia',r'武侠|江湖|wuxia'),('fantasy',r'奇幻|魔法|fantasy')]:
        if re.search(pattern,text,re.I):tags.add(tag)
    return tags


def configure_world_catalog(pack_dir: Path, libraries: list[SkillLibrary], router, *, preserve_initial: bool = False) -> dict:
    if not libraries:return {'configured':False,'warnings':[]}
    pack=load_pack(pack_dir)
    text=world_text(pack);tags=setting_tags(text)
    profile_path=pack_dir/'character_profile.json'
    profile=json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.is_file() else {}
    strong=profile.get('power') in ('master','legendary') or bool(re.search(r'(?:你|主角|玩家|角色)[^。\n]{0,180}(?:强大|资深|传奇|大法师|大师|高阶|精通)',text))
    limited=bool(profile.get('limitations')) or bool(re.search(r'失去(?:全部)?(?:魔力|能力)|无法施法|能力被封印|尚未学会',text))
    strong=strong and not limited
    mastered_schools=set(profile.get('schools') or [])
    definitions={};bound={}
    for library in libraries:
        for raw in library.skills:
            entry=bind_skill(library,raw,pack.state)
            if entry is None:continue
            if 'no_magic' in tags and raw.kind=='magic':continue
            definitions[entry.ref]=raw;bound[entry.ref]=entry
    # A skill whose prerequisite cannot bind is also unavailable, never made free/unlocked.
    while True:
        removed=[ref for ref,e in bound.items() if set(e.prerequisites)-bound.keys()]
        if not removed:break
        for ref in removed:bound.pop(ref)
    warnings=[];method='tags';model='';usage={};cost=0;selected=[];initial=[]
    catalog=[{'ref':ref,'name':e.skill.name,'kind':e.kind,'tier':e.tier,'school':e.school,'tags':e.tags,
        'requires_world_tags':definitions[ref].requires_world_tags,'excludes_world_tags':definitions[ref].excludes_world_tags,'brief':e.skill.brief} for ref,e in bound.items()]
    request={'phase':'skill_selection','allow_tools':False,'world':text,'existing_skills':[s.name for s in pack.skills],
        'candidates':catalog,'world_tags':sorted(tags),'preserve_initial':preserve_initial}
    try:
        profile=router.profile('settler' if router.separated else 'narrator')
        if profile.provider in ('scripted','replay'):raise ValueError('当前使用演示模型')
        response=router.complete('settler',request)
        data=extract_json(response.narrator.narrative if response.narrator else response.raw)
        if not isinstance(data.get('world_tags'),list) or not isinstance(data.get('skill_refs'),list) or not isinstance(data.get('initial_refs'),list):
            raise ValueError('选择结果缺少 world_tags/skill_refs/initial_refs 数组')
        proposed={str(tag) for tag in data['world_tags']}
        if 'no_magic' in tags:proposed.discard('magic');proposed.add('no_magic')
        tags |= proposed
        selected=list(dict.fromkeys(data['skill_refs']));initial=list(dict.fromkeys(data['initial_refs']))
        for ref in [*selected,*initial]:
            if not isinstance(ref,str) or ref not in bound:raise ValueError(f'模型引用了不存在或资源不兼容的技能：{ref}')
            raw=definitions[ref]
            if set(raw.requires_world_tags)-tags or set(raw.excludes_world_tags)&tags:raise ValueError(f'技能与世界设定不兼容：{ref}')
        method='llm';model=response.model;usage=response.usage;cost=response.cost_usd
        reason=str(data.get('reason') or '按角色背景和世界设定匹配')[:600]
    except Exception as exc:
        reason='按现有世界标签保守匹配；初始掌握依据主角背景。'
        warnings.append(f'技能库匹配未使用有效模型结果（{str(exc)[:160]}），已按设定标签匹配。')
        compatible=[e for ref,e in bound.items() if not(set(definitions[ref].requires_world_tags)-tags) and not(set(definitions[ref].excludes_world_tags)&tags)]
        schools={e.school for e in compatible if e.school in text}
        if 'magic' in tags:schools|={e.school for e in compatible if e.kind=='magic'}
        if not schools:schools={'身法','拳掌'}
        selected=[e.ref for e in compatible if e.school in schools]
        if strong:initial=list(selected)
        else:initial=[ref for ref in selected if bound[ref].tier=='low'][:3]
    if strong and not preserve_initial:
        compatible=[ref for ref,e in bound.items() if not(set(definitions[ref].requires_world_tags)-tags) and not(set(definitions[ref].excludes_world_tags)&tags)]
        schools=mastered_schools or {bound[ref].school for ref in compatible if bound[ref].school in text}
        if not schools:
            schools={bound[ref].school for ref in compatible if bound[ref].kind==('magic' if 'magic' in tags else 'martial')}
        granted=[ref for ref in compatible if bound[ref].school in schools]
        initial=list(dict.fromkeys([*initial,*granted]));selected=list(dict.fromkeys([*selected,*granted]))
        reason += '；按主角已精通背景补齐流派与中高级技能。'
    def closure(refs):
        result=set(refs)
        while True:
            parents={p for ref in result for p in bound[ref].prerequisites}
            if parents<=result:return result
            result |= parents
    initial_set=set() if preserve_initial else closure(initial)
    selected_set=closure([*selected,*initial_set])
    # Referenced prerequisites must satisfy the same world requirements.
    for ref in selected_set:
        raw=definitions[ref]
        if set(raw.requires_world_tags)-tags or set(raw.excludes_world_tags)&tags:
            raise ValueError(f'前置技能不符合世界：{ref}')
    snapshots=[bound[ref] for ref in sorted(selected_set)]
    if preserve_initial:
        old={entry.ref:entry for entry in pack.skill_catalog}
        snapshots=list({**{entry.ref:entry for entry in snapshots},**old}.values())
    base=list(pack.skills)
    ids={s.id for s in base};names={s.name.casefold() for s in base}
    for ref in sorted(initial_set):
        entry=bound[ref]
        if entry.skill.id in ids or entry.skill.name.casefold() in names:continue
        base.append(entry.skill);ids.add(entry.skill.id);names.add(entry.skill.name.casefold())
    selection={'method':method,'model':model,'reason':reason,'world_tags':sorted(tags),'pool_count':len(snapshots),
        'initial_refs':sorted(initial_set),'initial_count':len(initial_set),'warnings':warnings,'usage':usage,'cost_usd':cost,
        'library_versions':{lib.manifest.id:lib.manifest.version for lib in libraries}}
    path=pack_dir/'vocab/skill_catalog.json';skills_path=pack_dir/'vocab/skills.json'
    backups={p:p.read_bytes() if p.exists() else None for p in (path,skills_path)}
    try:
        path.write_text(json.dumps({'schema_version':1,'selection':selection,'skills':[e.model_dump(mode='json') for e in snapshots]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        skills_path.write_text(json.dumps({'skills':[s.model_dump(mode='json') for s in base]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        load_pack(pack_dir)
    except BaseException:
        for p,old in backups.items():
            if old is None:p.unlink(missing_ok=True)
            else:p.write_bytes(old)
        raise
    return {'configured':True,**selection}
