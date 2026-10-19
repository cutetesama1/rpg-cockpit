"""Read-only world-catalog queries and immutable-snapshot validation."""
from __future__ import annotations
import math,re
from .contracts import CatalogSkill, ContentPack, SkillSpec


def known_refs(catalog: list[CatalogSkill], skills: list[SkillSpec]) -> set[str]:
    ids={s.id for s in skills};names={s.name.casefold() for s in skills}
    return {entry.ref for entry in catalog if entry.skill.id in ids or entry.skill.name.casefold() in names}


def candidates(catalog: list[CatalogSkill], text: str, limit: int = 24) -> list[CatalogSkill]:
    def score(entry):
        names=[entry.skill.name,*entry.aliases]
        exact=sum(100 for name in names if name and name in text)
        tags=sum(8 for tag in [entry.school,*entry.tags] if len(tag)>1 and tag in text)
        return exact+tags
    return sorted(catalog,key=lambda entry:(-score(entry), {'low':0,'mid':1,'high':2}[entry.tier],entry.ref))[:limit]


def learning_signal(text: str) -> bool:
    return bool(re.search(r"学会|掌握|习得|领悟|学到了|学成|修成",text))


def validate_catalog(pack: ContentPack) -> list[str]:
    entries=pack.skill_catalog;errors=[]
    by_ref={entry.ref:entry for entry in entries}
    if len(by_ref)!=len(entries):errors.append("世界技能目录 ref 重复")
    if len({e.skill.id for e in entries})!=len(entries):errors.append("世界技能目录技能 id 重复")
    fields=pack.state.by_id();base={s.id:s for s in pack.skills}
    for e in entries:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}",e.skill.id):errors.append(f"预设技能 id 不合法：{e.ref}")
        if e.ref != f"{e.library_id}:{e.template_id}":errors.append(f"预设技能来源不一致：{e.ref}")
        if not e.instruction.strip() or not e.skill.action_text.strip():errors.append(f"预设技能缺少固定指令：{e.ref}")
        if not e.skill.name.strip() or not 0<=e.skill.cooldown<=99 or not e.skill.targets or set(e.skill.targets)-{'self','enemy','scene','item','npc','any','all','ally'}:errors.append(f"预设技能名称、冷却或目标不合法：{e.ref}")
        if set(e.prerequisites)-by_ref.keys():errors.append(f"预设技能缺少前置：{e.ref}")
        for key,amount in e.skill.cost.items():
            if key not in fields or fields[key].type not in ('int','float') or not math.isfinite(amount) or amount<0:errors.append(f"预设技能消耗不合法：{e.ref}/{key}")
        if e.skill.id in base and e.skill != base[e.skill.id]:errors.append(f"预设技能不能改写定义：{e.ref}")
    visiting=set();visited=set()
    def visit(ref):
        if ref in visiting:raise ValueError('世界技能目录前置循环')
        if ref in visited or ref not in by_ref:return
        visiting.add(ref)
        for parent in by_ref[ref].prerequisites:visit(parent)
        visiting.remove(ref);visited.add(ref)
    try:
        for ref in by_ref:visit(ref)
    except (ValueError,RecursionError):errors.append('世界技能目录前置循环或过深')
    return errors
