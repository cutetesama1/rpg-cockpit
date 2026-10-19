import StateEditor from "./StateEditor";
import { useEffect, useState } from "react";
import {
  applyWorldDraft,
  generateWorldDraft,
  getBuilderPrompt,
  parseWorldDraft,
} from "../api";
import type { BuilderDraft, BuilderSummary } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 创建成功后刷新主界面（游戏库 / 会话 / 世界）。 */
  onCreated: () => void;
  /** 当前叙事模型标签，用来提示「草稿由谁拆的」。 */
  modelLabel: string;
}

type Tab = "ai" | "paste" | "prompt";

const PROMPT_LABELS: Record<string, string> = {
  pre: "前置",
  narrator: "叙事",
  settler: "结算",
};

/** 快速创建世界：把一段素材交给模型（或外部 AI）拆成完整内容包。 */
export default function QuickCreateDialog({ open, onClose, onCreated, modelLabel }: Props) {
  const [tab, setTab] = useState<Tab>("ai");
  const [material, setMaterial] = useState("");
  const [titleHint, setTitleHint] = useState("");
  const [extraRules, setExtraRules] = useState("");
  const [pasted, setPasted] = useState("");
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<BuilderDraft | null>(null);
  const [summary, setSummary] = useState<BuilderSummary | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setMessage(null);
    getBuilderPrompt()
      .then((view) => setPrompt(view.prompt))
      .catch((err) => setError(String(err)));
  }, [open]);

  const acceptDraft = (next: BuilderDraft, nextSummary?: BuilderSummary) => {
    setDraft(next);
    setSummary(
      nextSummary ?? {
        title: next.title,
        description: next.description,
        prompt_keys: Object.keys(next.prompts),
        prompt_lengths: Object.fromEntries(
          Object.entries(next.prompts).map(([key, text]) => [key, (text ?? "").length]),
        ),
        worldbook_count: next.worldbook.length,
        skill_count: next.skills.length,
        warnings: next.warnings,
      },
    );
    setTitle(next.title || titleHint || "");
    setError(null);
  };

  const generate = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await generateWorldDraft(material, titleHint, extraRules);
      acceptDraft(result.draft, result.summary);
      setMessage(`草稿已生成（${result.model || modelLabel}）`);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const parse = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await parseWorldDraft(pasted);
      acceptDraft(result.draft, result.summary);
      setMessage("已解析粘贴的 JSON");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch (err) {
      setError(`复制失败：${String(err)}`);
    }
  };

  const create = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await applyWorldDraft(draft, title.trim());
      setMessage(`已创建「${result.world.title}」，正在进入…`);
      onCreated();
      setDraft(null);
      setSummary(null);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;
  return (
    <div className="modal-mask" role="dialog" aria-modal="true">
      <div className="modal builder-modal">
        <div className="modal-head">
          <h2>✨ 快速创建世界</h2>
          <button className="icon-btn" title="关闭" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="hint">
          把一段完整素材交给模型，拆成「前置 / 叙事 / 结算」三份提示词 + 世界书 + 技能，
          一次建成新游戏。生成的草稿可以先在这里看，创建后还能在世界构筑里细调。
        </p>

        <div className="tab-row">
          <button className={`tab${tab === "ai" ? " active" : ""}`} onClick={() => setTab("ai")}>
            让模型生成
          </button>
          <button
            className={`tab${tab === "paste" ? " active" : ""}`}
            onClick={() => setTab("paste")}
          >
            粘贴 AI 输出
          </button>
          <button
            className={`tab${tab === "prompt" ? " active" : ""}`}
            onClick={() => setTab("prompt")}
          >
            复制提示词
          </button>
        </div>

        {tab === "ai" && (
          <div className="editor-body">
            <label>
              素材（世界观 / 剧情 / 规则 / 人物 / 场景，可以很零散）
              <textarea
                className="edit-textarea"
                rows={8}
                value={material}
                placeholder={"例如：一座漂在黑海上的城市，居民用记忆点灯……\n把已有的设定、想玩的剧情、数值规则都可以直接贴进来。"}
                onChange={(event) => setMaterial(event.target.value)}
              />
            </label>
            <div className="save-form-row">
              <label>
                作品名（可选）
                <input
                  value={titleHint}
                  placeholder="留空让模型起名"
                  onChange={(event) => setTitleHint(event.target.value)}
                />
              </label>
              <label>
                额外要求（可选）
                <input
                  value={extraRules}
                  placeholder="例如：偏悬疑、不要战斗"
                  onChange={(event) => setExtraRules(event.target.value)}
                />
              </label>
            </div>
            <div className="modal-actions">
              <span className="hint">使用当前叙事模型：{modelLabel}</span>
              <button className="primary" disabled={busy || material.trim().length < 20} onClick={() => void generate()}>
                {busy ? "生成中…" : "生成草稿"}
              </button>
            </div>
          </div>
        )}

        {tab === "paste" && (
          <div className="editor-body">
            <label>
              把 AI 输出的 JSON 粘到这里
              <textarea
                className="edit-textarea"
                rows={8}
                value={pasted}
                placeholder='{"title": "…", "prompts": {"pre": "…", "narrator": "…", "settler": "…"}, "worldbook": [...], "skills": [...]}'
                onChange={(event) => setPasted(event.target.value)}
              />
            </label>
            <div className="modal-actions">
              <span className="hint">支持带 markdown 代码块或前后解释的输出，会自动找 JSON。</span>
              <button className="primary" disabled={busy || !pasted.trim()} onClick={() => void parse()}>
                {busy ? "解析中…" : "解析草稿"}
              </button>
            </div>
          </div>
        )}

        {tab === "prompt" && (
          <div className="editor-body">
            <label>
              世界构筑提示词（复制给任意 AI，把素材附在后面）
              <textarea className="edit-textarea builder-prompt" rows={12} readOnly value={prompt} />
            </label>
            <div className="modal-actions">
              <span className="hint">AI 输出后，回到「粘贴 AI 输出」页签导入。</span>
              <button className="ghost" onClick={() => void copyPrompt()}>
                {copied ? "已复制 ✓" : "复制提示词"}
              </button>
            </div>
          </div>
        )}

        {error && <p className="modal-message bad">{error}</p>}
        {message && !error && <p className="modal-message ok">{message}</p>}

        {draft && summary && (
          <section className="builder-preview">
            <div className="builder-preview-head">
              <h3>草稿预览</h3>
              <span className="badge">前置/叙事/结算 + 世界书 {summary.worldbook_count} + 技能 {summary.skill_count}</span>
            </div>
            <div className="save-form-row">
              <label>
                作品名
                <input value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label>
                简介
                <input value={draft.description} readOnly />
              </label>
            </div>
            <div className="builder-meta">
              {summary.prompt_keys.map((key) => (
                <span className="badge" key={key}>
                  {PROMPT_LABELS[key] ?? key} {summary.prompt_lengths[key] ?? 0} 字
                </span>
              ))}
            </div>
            {draft.state && <details className="advanced-box" open><summary>基础数值 · 创建前自定义</summary><StateEditor value={draft.state} onChange={state=>setDraft({...draft,state})} disabled={busy}/></details>}
            <div className="builder-columns">
              <div>
                <p className="sidebar-title">世界书</p>
                {draft.worldbook.length === 0 && <p className="empty">没有世界书条目（只有模板默认世界观）。</p>}
                <ul className="builder-list">
                  {draft.worldbook.map((entry) => (
                    <li key={entry.id}>
                      <strong>{entry.title}</strong>
                      {entry.always_on && <span className="badge">常驻</span>}
                      {entry.category && <span className="badge muted">{entry.category}</span>}
                      <small>{entry.keywords.length ? `关键词：${entry.keywords.join(" / ")}` : "无关键词"}</small>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="sidebar-title">技能</p>
                {draft.skills.length === 0 && <p className="empty">没有技能（模板默认无技能）。</p>}
                <ul className="builder-list">
                  {draft.skills.map((skill) => (
                    <li key={skill.id}>
                      <strong>{skill.name}</strong>
                      {skill.category && <span className="badge muted">{skill.category}</span>}
                      <small>
                        {skill.brief || skill.description}
                        {Object.keys(skill.cost).length
                          ? ` · 消耗 ${Object.entries(skill.cost)
                              .map(([key, value]) => `${key} ${value}`)
                              .join(" ")}`
                          : " · 无消耗"}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <details className="advanced-box">
              <summary>查看三份提示词全文</summary>
              {(["pre", "narrator", "settler"] as const).map((key) =>
                draft.prompts[key] ? (
                  <div key={key}>
                    <p className="sidebar-title">{PROMPT_LABELS[key]}</p>
                    <pre className="builder-prompt">{draft.prompts[key]}</pre>
                  </div>
                ) : null,
              )}
            </details>
            {draft.warnings.length > 0 && (
              <div className="modal-message bad">
                <strong>自动修正了 {draft.warnings.length} 处：</strong>
                <ul>
                  {draft.warnings.slice(0, 6).map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="muted small">已安装的技能库会在创建时按世界与角色背景匹配。强大角色可直接掌握大量中高级技能，学徒则按背景分配。</p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setDraft(null)}>
                丢弃草稿
              </button>
              <button className="primary" disabled={busy || !title.trim()} onClick={() => void create()}>
                {busy ? "创建中…" : "创建并进入这个世界"}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
