import StateEditor from "./StateEditor";
import { useEffect, useState } from "react";
import { cloneGame, savePrompts, saveSkills, saveWorldbook, saveWorldState } from "../api";
import type { WorldSkill, WorldView, WorldbookEntry } from "../types";

type Tab = "worldbook" | "skills" | "prompts" | "state";

interface Props {
  open: boolean;
  onClose: () => void;
  world: WorldView | null;
  onReload: () => Promise<void> | void;
  /** 复制为新游戏后刷新主界面（新包已切换为当前游戏）。 */
  onGameChanged: () => void;
}

function costToText(cost: Record<string, number>): string {
  return Object.entries(cost)
    .map(([field, value]) => `${field}:${value}`)
    .join(", ");
}

function parseCost(text: string): Record<string, number> {
  const cost: Record<string, number> = {};
  for (const piece of text.split(/[,，\s]+/)) {
    if (!piece) continue;
    const [field, raw] = piece.split(/[:：=]/);
    const value = Number(raw);
    if (field && Number.isFinite(value)) cost[field.trim()] = value;
  }
  return cost;
}

function listToText(items: string[]): string {
  return items.join(", ");
}

function textToList(text: string): string[] {
  return text
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const EMPTY_ENTRY: WorldbookEntry = {
  id: "",
  title: "",
  content: "",
  keywords: [],
  always_on: false,
  enabled: true,
  priority: 0,
  category: "",
};

const EMPTY_SKILL: WorldSkill = {
  id: "",
  name: "",
  description: "",
  cost: {},
  cooldown: 0,
  targets: ["scene"],
  action_text: "",
  effect_hint: "",
  brief: "",
  category: "其他",
  color: null,
};

export default function WorldDialog({
  open,
  onClose,
  world,
  onReload,
  onGameChanged,
}: Props) {
  const [tab, setTab] = useState<Tab>("worldbook");
  const [entries, setEntries] = useState<WorldbookEntry[]>([]);
  const [skills, setSkills] = useState<WorldSkill[]>([]);
  const [prompts, setPrompts] = useState({ pre: "", narrator: "", settler: "" });
  const [stateConfig,setStateConfig] = useState<WorldView["state"] | null>(null);
  const [currentValues,setCurrentValues] = useState<WorldView["current_values"]>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!world) return;
    setEntries(world.worldbook.map((entry) => ({ ...entry, keywords: [...entry.keywords] })));
    setSkills(
      world.skills.map((skill) => ({ ...skill, cost: { ...skill.cost }, targets: [...skill.targets] })),
    );
    setPrompts({ ...world.prompts });
    setStateConfig(structuredClone(world.state));
    setCurrentValues({...world.current_values});
    setMessage(null);
    setError(null);
  }, [world]);

  if (!open) return null;
  if (!world) {
    return (
      <div className="modal-mask" role="dialog" aria-modal="true">
        <div className="modal world-modal">
          <header className="modal-head">
            <h2>世界构筑</h2>
            <button className="ghost" onClick={onClose}>
              关闭
            </button>
          </header>
          <p className="modal-message bad">正在加载世界构筑…</p>
        </div>
      </div>
    );
  }

  const editable = world.editable;

  const patchEntry = (index: number, patch: Partial<WorldbookEntry>) => {
    setEntries((prev) => prev.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));
  };

  const patchSkill = (index: number, patch: Partial<WorldSkill>) => {
    setSkills((prev) => prev.map((skill, i) => (i === index ? { ...skill, ...patch } : skill)));
  };

  const save = async (kind: Tab) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (kind === "worldbook") {
        const response = await saveWorldbook(entries);
        setMessage(
          response.warnings.length
            ? `已保存；提示：${response.warnings.join("；")}`
            : "世界书已保存并生效（当前进度保留）。",
        );
      } else if (kind === "skills") {
        const response = await saveSkills(skills);
        setMessage(
          response.warnings.length
            ? `已保存；提示：${response.warnings.join("；")}`
            : "技能已保存并生效（当前进度保留）。",
        );
      } else if (kind === "state" && stateConfig) {
        const changedValues=Object.fromEntries(Object.entries(currentValues).filter(([key,value])=>value!==world.current_values[key]));
        await saveWorldState(stateConfig,changedValues);
        setMessage("基础数值已保存，当前进度保留。");
        onGameChanged();
      } else {
        const response = await savePrompts(prompts);
        setMessage(
          response.warnings.length
            ? `已保存；提示：${response.warnings.join("；")}`
            : "提示词已保存并生效（当前进度保留）。",
        );
      }
      await onReload();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const cloneForEdit = async () => {
    setBusy(true);
    setError(null);
    try {
      await cloneGame(world.pack_id, `${world.title} 副本`);
      setMessage("已复制为新游戏并切换过去，现在可以编辑了。");
      await onReload();
      onGameChanged();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-mask" role="dialog" aria-modal="true">
      <div className="modal world-modal">
        <header className="modal-head">
          <div>
            <h2>世界构筑 · {world.title}</h2>
            <p className="game-id">{world.pack_id}</p>
          </div>
          <button className="ghost" onClick={onClose}>
            关闭
          </button>
        </header>

        {!editable && (
          <div className="modal-banner">
            <span>内置内容包是只读的。想改世界书 / 技能 / 提示词，请先复制成自己的游戏。</span>
            <button className="primary" onClick={() => void cloneForEdit()} disabled={busy}>
              复制为新游戏
            </button>
          </div>
        )}

        <nav className="tab-row">
          <button className={tab === "state" ? "tab active" : "tab"} onClick={() => setTab("state")}>基础数值</button>
          <button className={tab === "worldbook" ? "tab active" : "tab"} onClick={() => setTab("worldbook")}>
            世界书 <span className="tab-count">{entries.length}</span>
          </button>
          <button className={tab === "skills" ? "tab active" : "tab"} onClick={() => setTab("skills")}>
            技能 <span className="tab-count">{skills.length}</span>
          </button>
          <button className={tab === "prompts" ? "tab active" : "tab"} onClick={() => setTab("prompts")}>
            前置 / 提示词
          </button>
        </nav>

        {message && <p className="modal-message ok">{message}</p>}
        {error && <p className="modal-message bad">{error}</p>}

        {tab === "state" && stateConfig && <div className="editor-body"><StateEditor value={stateConfig} onChange={setStateConfig} current={currentValues} onCurrent={setCurrentValues} disabled={!editable||busy}/><div className="modal-actions"><button className="primary" disabled={!editable||busy} onClick={()=>void save("state")}>{busy?"保存中…":"保存基础数值"}</button></div></div>}
        {tab === "worldbook" && (
          <div className="editor-body">
            <p className="hint">
              常驻条目每回合都注入；其它条目只有在玩家行动 / 场景文本里出现关键词时才注入。优先级越大越先注入。
            </p>
            {entries.map((entry, index) => (
              <article className="edit-card" key={`${entry.id}-${index}`}>
                <div className="edit-grid">
                  <label>
                    标题
                    <input value={entry.title} disabled={!editable} onChange={(e) => patchEntry(index, { title: e.target.value })} />
                  </label>
                  <label>
                    id
                    <input value={entry.id} disabled={!editable} onChange={(e) => patchEntry(index, { id: e.target.value })} />
                  </label>
                  <label>
                    分类
                    <input value={entry.category} disabled={!editable} onChange={(e) => patchEntry(index, { category: e.target.value })} />
                  </label>
                  <label>
                    优先级
                    <input
                      type="number"
                      value={entry.priority}
                      disabled={!editable}
                      onChange={(e) => patchEntry(index, { priority: Number(e.target.value) || 0 })}
                    />
                  </label>
                </div>
                <label>
                  关键词（逗号分隔，命中任意一个就注入）
                  <input
                    value={listToText(entry.keywords)}
                    disabled={!editable}
                    onChange={(e) => patchEntry(index, { keywords: textToList(e.target.value) })}
                  />
                </label>
                <label>
                  内容
                  <textarea
                    rows={3}
                    value={entry.content}
                    disabled={!editable}
                    onChange={(e) => patchEntry(index, { content: e.target.value })}
                  />
                </label>
                <div className="edit-row">
                  <label className="inline">
                    <input
                      type="checkbox"
                      checked={entry.always_on}
                      disabled={!editable}
                      onChange={(e) => patchEntry(index, { always_on: e.target.checked })}
                    />
                    常驻
                  </label>
                  <label className="inline">
                    <input
                      type="checkbox"
                      checked={entry.enabled}
                      disabled={!editable}
                      onChange={(e) => patchEntry(index, { enabled: e.target.checked })}
                    />
                    启用
                  </label>
                  <button
                    className="ghost danger"
                    disabled={!editable}
                    onClick={() => setEntries((prev) => prev.filter((_, i) => i !== index))}
                  >
                    删除条目
                  </button>
                </div>
              </article>
            ))}
            <div className="modal-actions">
              <button className="ghost" disabled={!editable} onClick={() => setEntries((prev) => [...prev, { ...EMPTY_ENTRY }])}>
                添加条目
              </button>
              <button className="primary" disabled={!editable || busy} onClick={() => void save("worldbook")}>
                保存世界书
              </button>
            </div>
          </div>
        )}

        {tab === "skills" && (
          <div className="editor-body">
            <p className="hint">技能是内容包资产：消耗字段必须是已声明的状态字段；冷却按回合算；「使用」按钮会用 action_text 提交。</p>
            {skills.map((skill, index) => (
              <article className="edit-card" key={`${skill.id}-${index}`}>
                <div className="edit-grid">
                  <label>
                    名称
                    <input value={skill.name} disabled={!editable} onChange={(e) => patchSkill(index, { name: e.target.value })} />
                  </label>
                  <label>
                    id
                    <input value={skill.id} disabled={!editable} onChange={(e) => patchSkill(index, { id: e.target.value })} />
                  </label>
                  <label>
                    分类
                    <input value={skill.category ?? ""} disabled={!editable} onChange={(e) => patchSkill(index, { category: e.target.value })} />
                  </label>
                  <label>
                    冷却（回合）
                    <input
                      type="number"
                      value={skill.cooldown}
                      disabled={!editable}
                      onChange={(e) => patchSkill(index, { cooldown: Number(e.target.value) || 0 })}
                    />
                  </label>
                </div>
                <div className="edit-grid">
                  <label>
                    消耗（field:value, 逗号分隔）
                    <input
                      value={costToText(skill.cost)}
                      disabled={!editable}
                      onChange={(e) => patchSkill(index, { cost: parseCost(e.target.value) })}
                    />
                  </label>
                  <label>
                    目标（self/enemy/scene/item/npc，逗号分隔）
                    <input
                      value={listToText(skill.targets)}
                      disabled={!editable}
                      onChange={(e) => patchSkill(index, { targets: textToList(e.target.value) })}
                    />
                  </label>
                </div>
                <label>
                  简述（收起时显示）
                  <input value={skill.brief ?? ""} disabled={!editable} onChange={(e) => patchSkill(index, { brief: e.target.value })} />
                </label>
                <label>
                  描述
                  <textarea rows={2} value={skill.description} disabled={!editable} onChange={(e) => patchSkill(index, { description: e.target.value })} />
                </label>
                <div className="edit-grid">
                  <label>
                    行动描述（点「使用」时提交给 GM 的文字）
                    <input value={skill.action_text} disabled={!editable} onChange={(e) => patchSkill(index, { action_text: e.target.value })} />
                  </label>
                  <label>
                    效果提示
                    <input value={skill.effect_hint ?? ""} disabled={!editable} onChange={(e) => patchSkill(index, { effect_hint: e.target.value })} />
                  </label>
                </div>
                <div className="edit-row">
                  <button
                    className="ghost danger"
                    disabled={!editable}
                    onClick={() => setSkills((prev) => prev.filter((_, i) => i !== index))}
                  >
                    删除技能
                  </button>
                </div>
              </article>
            ))}
            <div className="modal-actions">
              <button className="ghost" disabled={!editable} onClick={() => setSkills((prev) => [...prev, { ...EMPTY_SKILL, cost: {} }])}>
                添加技能
              </button>
              <button className="primary" disabled={!editable || busy} onClick={() => void save("skills")}>
                保存技能
              </button>
            </div>
          </div>
        )}

        {tab === "prompts" && (
          <div className="editor-body">
            <p className="hint">前置提示词每回合都拼在最前面，用来锁定世界观基调；叙事/结算提示词拼在它后面。</p>
            <label>
              前置提示词（prompts/pre.md）
              <textarea
                rows={6}
                value={prompts.pre}
                disabled={!editable}
                onChange={(e) => setPrompts((prev) => ({ ...prev, pre: e.target.value }))}
              />
            </label>
            <label>
              叙事提示词（prompts/narrator.md）
              <textarea
                rows={8}
                value={prompts.narrator}
                disabled={!editable}
                onChange={(e) => setPrompts((prev) => ({ ...prev, narrator: e.target.value }))}
              />
            </label>
            <label>
              结算提示词（prompts/settler.md）
              <textarea
                rows={8}
                value={prompts.settler}
                disabled={!editable}
                onChange={(e) => setPrompts((prev) => ({ ...prev, settler: e.target.value }))}
              />
            </label>
            <div className="modal-actions">
              <button className="primary" disabled={!editable || busy} onClick={() => void save("prompts")}>
                保存提示词
              </button>
            </div>
          </div>
        )}

        <footer className="modal-foot">
          <span>{editable ? "这是你自己的游戏，改动直接写进内容包目录。" : "内置包只读：复制后编辑。"}</span>
          <span>保存后会话会重置到开场，让新设定立刻生效。</span>
        </footer>
      </div>
    </div>
  );
}
