import { useMemo, useState } from "react";
import type { Skill } from "../types";

interface Props {
  title: string;
  skills: Skill[];
  busy: boolean;
  /** 已勾选、将随本次输入一起结算的技能 id（同一回合可多选）。 */
  picked: string[];
  onToggle: (skillId: string) => void;
}

function costText(skill: Skill): string {
  const entries = Object.entries(skill.cost ?? {});
  if (entries.length === 0) return "";
  return `耗 ${entries.map(([field, amount]) => `${field} ${amount}`).join(" / ")}`;
}

function shortMeta(skill: Skill): string {
  const parts = [costText(skill)];
  if (skill.cooldown > 0) {
    parts.push(
      skill.cooldown_remaining && skill.cooldown_remaining > 0
        ? `冷却中 ${skill.cooldown_remaining}`
        : `冷却 ${skill.cooldown}`,
    );
  }
  return parts.filter(Boolean).join(" · ");
}

function brief(skill: Skill): string {
  return skill.brief || skill.effect_hint || "";
}

export default function SkillCards({ title, skills, busy, picked, onToggle }: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, Skill[]>();
    for (const skill of skills) {
      const key = skill.category?.trim() || "其他";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(skill);
    }
    return Array.from(map.entries());
  }, [skills]);

  // 分类默认展开；子技能默认只看简表，点开才看详情。
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [openSkills, setOpenSkills] = useState<Record<string, boolean>>({});

  const toggleGroup = (name: string) =>
    setCollapsedGroups((prev) => ({ ...prev, [name]: !prev[name] }));
  const toggleSkill = (id: string) =>
    setOpenSkills((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <section className="panel panel-compact">
      <h2>{title}</h2>
      <div className="skill-groups">
        {groups.map(([name, items]) => {
          const open = !collapsedGroups[name];
          return (
            <div className="skill-group" key={name}>
              <button
                className="skill-group-head"
                onClick={() => toggleGroup(name)}
                aria-expanded={open}
              >
                <span className="chevron">{open ? "▾" : "▸"}</span>
                <span className="skill-group-name">{name}</span>
                <span className="skill-group-count">{items.length}</span>
              </button>

              {open && (
                <div className="skill-group-body">
                  {items.map((skill) => {
                    const blocked = skill.available === false;
                    const expanded = Boolean(openSkills[skill.id]);
                    const selected = picked.includes(skill.id);
                    const meta = shortMeta(skill);
                    return (
                      <div
                        className={`skill-row${blocked ? " skill-blocked" : ""}${
                          expanded ? " skill-row-open" : ""
                        }${selected ? " skill-picked" : ""}`}
                        key={skill.id}
                      >
                        <div className="skill-row-main">
                          <button
                            className="skill-row-toggle"
                            onClick={() => toggleSkill(skill.id)}
                            aria-expanded={expanded}
                            title={expanded ? "收起详情" : "展开详情"}
                          >
                            <span className="skill-row-line">
                              <span className="skill-row-name">{skill.name}</span>
                              <span className="skill-row-brief">{brief(skill)}</span>
                            </span>
                            <span className="skill-row-meta">
                              {blocked ? skill.blocked_reason ?? "不可用" : meta || "无消耗"}
                            </span>
                          </button>

                          {expanded && (
                            <div className="skill-detail">
                              {skill.description && (
                                <p className="skill-detail-desc">{skill.description}</p>
                              )}
                              <dl className="skill-detail-list">
                                <div>
                                  <dt>消耗</dt>
                                  <dd>{costText(skill) || "无"}</dd>
                                </div>
                                <div>
                                  <dt>冷却</dt>
                                  <dd>
                                    {skill.cooldown > 0 ? `${skill.cooldown} 回合` : "无"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>目标</dt>
                                  <dd>{skill.targets.join(" / ") || "—"}</dd>
                                </div>
                                {skill.usable_when && (
                                  <div>
                                    <dt>可用条件</dt>
                                    <dd>{skill.usable_when}</dd>
                                  </div>
                                )}
                                {skill.effect_hint && (
                                  <div>
                                    <dt>效果</dt>
                                    <dd>{skill.effect_hint}</dd>
                                  </div>
                                )}
                                {skill.action_text && (
                                  <div>
                                    <dt>行动描述</dt>
                                    <dd>{skill.action_text}</dd>
                                  </div>
                                )}
                              </dl>
                              {blocked && skill.blocked_reason && (
                                <p className="skill-detail-blocked">{skill.blocked_reason}</p>
                              )}
                            </div>
                          )}
                        </div>

                        <button
                          className={`skill-pick${selected ? " on" : ""}`}
                          disabled={busy || blocked}
                          aria-pressed={selected}
                          onClick={() => onToggle(skill.id)}
                          title={
                            blocked
                              ? skill.blocked_reason ?? "不可用"
                              : selected
                                ? `取消「${skill.name}」（取消后不扣消耗）`
                                : `勾选「${skill.name}」，随本次发送一起结算`
                          }
                        >
                          {selected ? "已选" : "选用"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
