import { useEffect, useMemo, useRef, useState } from "react";
import { getSkillLibraries, getSkillLibrary, getWorldSkillCatalog, importSkillLibrary, installStandardSkills, matchWorldSkillCatalog, repairInitialSkills } from "../api";
import type { CatalogEntry, SkillLibraryInfo, WorldSkillCatalog } from "../types";
const KIND = { martial: "武技", magic: "魔法" };
const TIER = { low: "低级", mid: "中级", high: "高级" };

export default function SkillLibraryPanel({ onChanged }: { onChanged: () => Promise<void> | void }) {
  const [libraries, setLibraries] = useState<SkillLibraryInfo[]>([]);
  const [world, setWorld] = useState<WorldSkillCatalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("world");
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [tier, setTier] = useState("");
  const [page, setPage] = useState(0);
  const file = useRef<HTMLInputElement>(null);
  const reload = async () => {
    const [libs, current] = await Promise.all([getSkillLibraries(), getWorldSkillCatalog()]);
    setLibraries(libs.libraries); setWorld(current);
    return current;
  };
  useEffect(() => { void reload().catch(err => { setMessage(String(err)); setError(true); }); }, []);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    if (scope === "world") setEntries(world?.skills ?? []);
    else {
      setEntries([]);
      void getSkillLibrary(scope).then(lib => {
        if (alive) setEntries(lib.skills.map(entry => ({ ...entry, ref: `${lib.manifest.id}:${entry.id}`, library_id: lib.manifest.id, template_id: entry.id,
          skill: { ...entry.skill, cost: entry.resource_cost } })));
      }).catch(err => { if (alive) { setMessage(String(err)); setError(true); } });
    }
    return () => { alive = false; };
  }, [open, scope, world]);
  useEffect(() => { setPage(0); }, [scope, query, kind, tier]);
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false); } };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open]);
  const run = async (job: () => Promise<unknown>, success: string) => {
    setBusy(true); setError(false); setMessage("正在处理…");
    try { await job(); await reload(); await onChanged(); setMessage(success); }
    catch (err) { setMessage(String(err)); setError(true); }
    finally { setBusy(false); }
  };
  const filtered = useMemo(() => entries.filter(entry => (!kind || entry.kind === kind) && (!tier || entry.tier === tier) &&
    (!query.trim() || `${entry.skill.name} ${entry.school} ${entry.skill.description} ${entry.ref}`.toLowerCase().includes(query.trim().toLowerCase()))), [entries, query, kind, tier]);
  const visible = filtered.slice(page*30, page*30+30);
  return <section className="settings-section skill-library-settings">
    <h3>技能库 · 预设技能</h3>
    <p className="muted small">已安装 {libraries.length} 个库，共 {libraries.reduce((n,item) => n+item.count,0)} 个技能。新建世界时按初始设定匹配，已掌握数量由角色背景决定。</p>
    <div className="skill-library-actions">
      <button type="button" disabled={busy || libraries.some(lib => lib.id === "standard-martial-magic")} onClick={() => void run(installStandardSkills, "300技能库已安装。新建世界会按设定配置，也可为当前世界匹配可学池。")}>导入300技能库</button>
      <button type="button" disabled={busy} onClick={() => file.current?.click()}>导入技能库 ZIP</button>
      <button type="button" onClick={() => setOpen(true)}>浏览技能库</button>
      <button type="button" disabled={busy||!world?.editable||!libraries.length} onClick={()=>void run(repairInitialSkills,"已按初始背景补齐技能，当前剧情和资源保留。")}>补齐初始技能</button>
      <a href="/api/skill-libraries/template.zip" download>下载作者格式模板</a>
    </div>
    <input ref={file} type="file" accept=".zip,application/zip" hidden onChange={event => {
      const selected = event.target.files?.[0]; event.target.value = "";
      if (selected) void run(() => importSkillLibrary(selected), "技能库已导入，可在创建世界时使用。");
    }} />
    <p className="muted small">当前世界可学池：{world?.skills.length ?? 0} 个；已掌握 {world?.skills.filter(entry => entry.known).length ?? 0} 个预设技能。</p>
    <button type="button" disabled={busy || !libraries.length || !world?.editable} onClick={() => void run(matchWorldSkillCatalog, "已按当前设定匹配可学池，当前进度与已掌握技能保留。")}>{busy ? "正在匹配／导入…" : "为当前世界匹配技能池"}</button>
    <p className="muted small">匹配当前世界会保留进度；内置游戏请先复制为可编辑世界。</p>
    {world?.selection.reason && <p className="muted small">匹配依据：{world.selection.reason}</p>}
    {world?.selection.warnings?.map(note => <p className="muted small" key={note}>{note}</p>)}
    {message && <p role="status" className={`drawer-message ${error ? "bad" : "ok"}`}>{message}</p>}
    {open && <div className="modal-mask skill-library-modal-mask" role="dialog" aria-modal="true" aria-label="技能库浏览" onClick={event => { event.stopPropagation(); setOpen(false); }}>
      <div className="modal skill-library-modal" onClick={event => event.stopPropagation()}>
        <header className="modal-head"><h2>技能库</h2><button type="button" onClick={() => setOpen(false)}>关闭技能库</button></header>
        <div className="skill-library-filters">
          <label>来源<select aria-label="技能来源" value={scope} onChange={event => setScope(event.target.value)}><option value="world">当前世界可学池</option>{libraries.map(lib => <option key={lib.id} value={lib.id}>{lib.title}（{lib.count}）</option>)}</select></label>
          <label>类型<select aria-label="技能类型" value={kind} onChange={event => setKind(event.target.value)}><option value="">全部类型</option><option value="martial">武技</option><option value="magic">魔法</option></select></label>
          <label>等级<select aria-label="技能等级" value={tier} onChange={event => setTier(event.target.value)}><option value="">全部等级</option><option value="low">低级</option><option value="mid">中级</option><option value="high">高级</option></select></label>
          <label>搜索<input aria-label="搜索技能" value={query} onChange={event => setQuery(event.target.value)} placeholder="名称、流派或说明" /></label>
        </div>
        <p className="muted">共 {filtered.length} 个 · 第 {page+1} / {Math.max(1,Math.ceil(filtered.length/30))} 页</p>
        <div className="skill-library-list">{visible.map(entry => <details key={entry.ref}>
          <summary><strong>{entry.skill.name}</strong><span>{KIND[entry.kind]} · {TIER[entry.tier]} · {entry.school}</span>{scope === "world" && <em>{entry.known ? "已掌握" : entry.learnable ? "可学习" : "需前置技能"}</em>}</summary>
          <p>{entry.skill.description}</p><p>行动：{entry.skill.action_text}</p><p>消耗：{Object.entries(entry.skill.cost).map(([key,value]) => `${key} ${value}`).join(" / ") || "无"} · 冷却 {entry.skill.cooldown} 回合</p>
          <p>固定执行说明：{entry.instruction}</p><p className="muted small">引用：{entry.ref}{entry.prerequisites.length > 0 && ` · 前置：${entry.prerequisites.join("、")}`}</p>
        </details>)}</div>
        {!filtered.length && <p className="muted">暂无匹配技能。可以先导入技能库，再按世界设定配置。</p>}
        <footer className="skill-library-pagination"><button type="button" disabled={page===0} onClick={() => setPage(page-1)}>上一页</button><button type="button" disabled={(page+1)*30>=filtered.length} onClick={() => setPage(page+1)}>下一页</button></footer>
      </div>
    </div>}
  </section>;
}
