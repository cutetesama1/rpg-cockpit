import { useEffect, useState } from "react";
import { getSettings, postSettings, resetSettings, testSettings, probeModels } from "../api";
import type { LlmProfile, LlmRoles, ProviderView, SettingsUpdate, SettingsView, SpeechSettings, VoiceCharacter, VoiceView } from "../types";

const ROLE_INFO = [
  ["narrator", "叙事 AI · 前端", "生成正文、选项与叙述修订。"],
  ["settler", "结算 AI · 后端", "读取本轮玩家输入、最终叙述与当前状态，结算资源、技能和世界书。"],
  ["director", "剧情导演 AI", "独立连接，按场景和事件触发；在下方剧情导演中开启功能。"],
  ["setup", "世界构筑 AI", "根据你的设定生成游戏草稿。"],
  ["corrector", "数值纠正 AI", "只处理本次纠正说明，不携带历史对话。"],
  ["voice_cast", "NPC 识别 AI", "自动模式下识别本次叙述的说话人物和台词归属。"],
  ["arbiter", "裁定辅助 AI · 预留角色", "保留独立配置；当前玩家裁定由后端校验，不自动调用此模型。"],
] as const;
type Role = typeof ROLE_INFO[number][0];
interface Draft { profile: LlmProfile; source: string; endpoint: ProviderView & { api_key: string }; scripted: boolean }
const empty: ProviderView = { base_url: "", model: "", preset: "custom", reasoning_effort: "", timeout: 60, price_in: 0, price_out: 0, max_retries: 2, retry_backoff_ms: 500, has_key: false, key_hint: "" };
const speechDefault: SpeechSettings = { enabled: false, mode: "imported", base_url: "", model: "", voice: "alloy", speed: 1, timeout: 60, has_key: false, key_hint: "" };

export default function ModelConnections({ onChanged, packId }: { onChanged: () => void | Promise<void>; packId?: string }) {
  const [saved, setSaved] = useState<SettingsView | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [speech, setSpeech] = useState<SpeechSettings & { api_key?: string }>(speechDefault);
  const [characters, setCharacters] = useState<VoiceCharacter[]>([]);
  const [modelLists, setModelLists] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const reloadCharacters = () => fetch('/api/voice').then(r => r.json()).then((v: VoiceView) => setCharacters(v.characters));
  const load = (data: SettingsView) => {
    setSaved(data); setSpeech({ ...speechDefault, ...data.speech, api_key: "" });
    const next: Record<string, Draft> = {};
    for (const [role] of ROLE_INFO) {
      const profile = data.roles[role] ?? (data.roles.separated ? data.roles.settler : data.roles.narrator);
      const actual = role === 'settler' && !data.roles.separated ? data.roles.narrator : profile;
      const cfg = data.providers[`role_${role}`] ?? data.providers[actual.provider] ?? empty;
      next[role] = { source: actual.provider, profile: { ...actual }, endpoint: { ...cfg, model: actual.model || cfg.model, api_key: "" }, scripted: actual.provider === 'scripted' };
    }
    setDrafts(next);
  };
  useEffect(() => { let live = true; getSettings().then(d => { if (live) load(d); }).catch(e => { if (live) setMessage(String(e)); }); void reloadCharacters(); return () => { live = false; }; }, [packId]);
  const patch = (role: Role, changes: Partial<Draft>) => setDrafts(old => ({ ...old, [role]: { ...old[role], ...changes } }));
  const endpoint = (role: Role, changes: Partial<Draft['endpoint']>) => setDrafts(old => ({ ...old, [role]: { ...old[role], endpoint: { ...old[role].endpoint, ...changes } } }));
  const payload = (): SettingsUpdate => {
    const roles = { ...saved!.roles, separated: true } as LlmRoles;
    const providers: NonNullable<SettingsUpdate['providers']> = {};
    for (const [role] of ROLE_INFO) {
      const d = drafts[role];
      roles[role] = { ...d.profile, provider: d.scripted ? 'scripted' : `role_${role}`, model: d.endpoint.model.trim() };
      if (!d.scripted) providers[`role_${role}`] = {
        base_url: d.endpoint.base_url.trim(), model: d.endpoint.model.trim(), preset: d.endpoint.preset || 'custom',
        reasoning_effort: d.endpoint.reasoning_effort, timeout: d.endpoint.timeout, max_retries: d.endpoint.max_retries,
        retry_backoff_ms: d.endpoint.retry_backoff_ms, price_in: d.endpoint.price_in, price_out: d.endpoint.price_out,
        copy_from: d.source, ...(d.endpoint.api_key.trim() ? { api_key: d.endpoint.api_key.trim() } : {}),
      };
    }
    const { has_key, key_hint, api_key, ...voice } = speech;
    return { roles, providers, speech: { ...voice, ...(api_key?.trim() ? { api_key: api_key.trim() } : {}) } };
  };
  const save = async () => {
    setBusy(true); setMessage('');
    try { load(await postSettings(payload())); window.dispatchEvent(new Event('rpg-settings-changed')); await onChanged(); setMessage('全部角色连接与语音设置已保存，各角色 URL / API Key 互不覆盖。'); }
    catch (e) { setMessage(String(e)); } finally { setBusy(false); }
  };
  const test = async (role: Role) => {
    setBusy(true); setMessage('正在测试这一个角色的连接…');
    try { const r = await testSettings({ ...payload(), test_role: role }); setMessage(r.ok ? `连接成功：${r.provider} / ${r.model}` : `连接失败：${r.error}`); }
    catch (e) { setMessage(String(e)); } finally { setBusy(false); }
  };
  const probe = async (role: Role) => {
    setBusy(true); setMessage('正在读取此角色端点的模型列表…');
    try { const d = drafts[role]; const result = await probeModels({ base_url: d.endpoint.base_url.trim(), api_key: d.endpoint.api_key.trim(), provider: saved?.providers[`role_${role}`] ? `role_${role}` : d.source }); setModelLists(old => ({ ...old, [role]: result.models.map(m => m.id) })); setMessage(`已读取 ${result.count} 个模型，可在此角色的模型名称中选择。`); }
    catch (e) { setMessage(String(e)); } finally { setBusy(false); }
  };
  const updateCharacter = async (char: VoiceCharacter, change: Partial<VoiceCharacter>) => {
    if (!packId) return;
    try {
      const next = { ...char, ...change };
      const response = await fetch('/api/voice/character', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pack_id: packId, character_id: char.id, enabled: next.enabled, voice: next.voice }) });
      if (!response.ok) throw new Error('人物语音设置保存失败');
      const data = await response.json() as VoiceView; setCharacters(data.characters); window.dispatchEvent(new Event('rpg-voice-characters-changed'));
    } catch (e) { setMessage(String(e)); }
  };
  if (!saved) return <p className="muted">{message || '正在读取模型连接…'}</p>;
  return <section className="settings-section model-connections">
    <h3>模型 · 每个 AI 独立接口</h3>
    <p className="muted small">前端叙事、后端结算、剧情导演各有自己的 URL、API Key 和模型。Key 保存在本机后端，仅在调用时发送到你指定的接口；留空保留原 Key。旧连接会在保存时复制为独立配置。</p>
    {ROLE_INFO.map(([role, title, hint]) => {
      const d = drafts[role];
      return <details className="role-connection" key={role} open={role === 'narrator' || role === 'settler' || role === 'director'}>
        <summary>{title}<small>{d.scripted ? ' · 脚本演示' : ` · ${d.endpoint.model || '待配置'}`}</small></summary>
        <p className="muted small">{hint}</p>
        <label className="checkbox-row"><input type="checkbox" checked={!d.scripted} onChange={e => patch(role, { scripted: !e.target.checked })} /><span>启用此角色的独立 API（关闭使用脚本演示）</span></label>
        {!d.scripted && <>
          <label><span>供应商预设</span><select value={d.endpoint.preset || 'custom'} onChange={e => { const preset = saved.catalog.presets.find(p => p.id === e.target.value); endpoint(role, { preset: e.target.value, ...(preset?.base_url ? { base_url: preset.base_url } : {}) }); }}>{saved.catalog.presets.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
          <label><span>{title} · URL</span><input type="url" value={d.endpoint.base_url} placeholder="https://你的服务地址/v1" onChange={e => endpoint(role, { base_url: e.target.value })} /></label>
          <label><span>{title} · API Key {d.endpoint.has_key ? `（已保存 ${d.endpoint.key_hint}，留空保留）` : ''}</span><input type="password" autoComplete="new-password" value={d.endpoint.api_key} placeholder="本角色专用 API Key" onChange={e => endpoint(role, { api_key: e.target.value })} /></label>
          <label><span>模型名称</span><input list={`role-models-${role}`} value={d.endpoint.model} placeholder="填写或选择此端点的模型 ID" onChange={e => endpoint(role, { model: e.target.value })} /></label>
          <datalist id={`role-models-${role}`}>{Array.from(new Set([...(modelLists[role] ?? []), ...(saved.catalog.presets.find(p => p.id === d.endpoint.preset)?.models.map(m => m.id) ?? [])])).map(id => <option key={id} value={id}/>)}</datalist>
          <button type="button" className="ghost small" disabled={busy} onClick={() => void probe(role)}>读取此角色可用模型</button>
          <details><summary>参数与计费</summary>
            <div className="field-row"><label><span>温度</span><input type="number" min="0" max="2" step="0.1" value={d.profile.temperature} onChange={e => patch(role, { profile: { ...d.profile, temperature: Number(e.target.value) } })} /></label><label><span>输出上限（0 不限制）</span><input type="number" min="0" value={d.profile.max_tokens} onChange={e => patch(role, { profile: { ...d.profile, max_tokens: Number(e.target.value) } })} /></label></div>
            <label><span>思考强度</span><select value={d.endpoint.reasoning_effort} onChange={e => endpoint(role, { reasoning_effort: e.target.value })}>{saved.catalog.efforts.map(e => <option value={e.id} key={e.id}>{e.label}</option>)}</select></label>
            <div className="field-row"><label><span>超时（秒）</span><input type="number" min="1" value={d.endpoint.timeout} onChange={e => endpoint(role, { timeout: Number(e.target.value) })} /></label><label><span>重试（0—5）</span><input type="number" min="0" max="5" value={d.endpoint.max_retries} onChange={e => endpoint(role, { max_retries: Number(e.target.value) })} /></label></div>
            <div className="field-row"><label><span>输入价格 / 百万 token</span><input type="number" min="0" step="0.01" value={d.endpoint.price_in} onChange={e => endpoint(role, { price_in: Number(e.target.value) })} /></label><label><span>输出价格 / 百万 token</span><input type="number" min="0" step="0.01" value={d.endpoint.price_out} onChange={e => endpoint(role, { price_out: Number(e.target.value) })} /></label></div>
          </details>
        </>}
        <button type="button" className="ghost small" disabled={busy} onClick={() => void test(role)}>测试{title.split(' · ')[0]}连接</button>
      </details>;
    })}
    <section className="speech-settings">
      <h3>NPC 语音</h3>
      <label className="checkbox-row"><input type="checkbox" checked={speech.enabled} onChange={e => setSpeech({ ...speech, enabled: e.target.checked })} /><span>启用语音模型 API，只朗读 NPC 实际说出口的台词</span></label>
      {speech.enabled && <>
        <label><span>可朗读人物范围</span><select value={speech.mode} onChange={e => setSpeech({ ...speech, mode: e.target.value as SpeechSettings['mode'] })}><option value="imported">仅用户导入的 NPC</option><option value="automatic">后端 AI 自动识别人物并加入可朗读列表</option></select></label>
        <p className="muted small">仅导入模式保守匹配带姓名的台词，不额外调用识别模型；自动模式在叙述完成后调用 NPC 识别 AI，不带历史。归属不确定的台词跳过。旁白、心理与玩家台词不朗读。</p>
        <label><span>语音 URL（兼容 audio/speech）</span><input type="url" value={speech.base_url} placeholder="https://语音服务/v1 或完整 /audio/speech 地址" onChange={e => setSpeech({ ...speech, base_url: e.target.value })} /></label>
        <label><span>语音 API Key {speech.has_key ? `（已保存 ${speech.key_hint}，留空保留）` : ''}</span><input type="password" autoComplete="new-password" value={speech.api_key || ''} onChange={e => setSpeech({ ...speech, api_key: e.target.value })} /></label>
        <label><span>语音模型名称</span><input value={speech.model} onChange={e => setSpeech({ ...speech, model: e.target.value })} /></label>
        <div className="field-row"><label><span>默认音色 ID</span><input value={speech.voice} onChange={e => setSpeech({ ...speech, voice: e.target.value })} /></label><label><span>语速（0.25—4）</span><input type="number" min="0.25" max="4" step="0.05" value={speech.speed} onChange={e => setSpeech({ ...speech, speed: Number(e.target.value) })} /></label></div>
        <p className="muted small">音色 ID 由你的语音服务提供。保存后，对话下方可选择台词并播放；支持停止与重播。人物开关和音色在下方即时保存，各世界独立。</p>
        <button type="button" className="ghost small" onClick={() => void reloadCharacters().catch(e => setMessage(String(e)))}>刷新可朗读人物</button>
        <div className="voice-character-list">{characters.length ? characters.map(c => <div key={c.id} className="voice-character"><label className="checkbox-row"><input type="checkbox" checked={c.enabled} onChange={e => void updateCharacter(c, { enabled: e.target.checked })} /><span>{c.name} · {c.source === 'imported' ? '导入 NPC' : '自动识别'}</span></label><input aria-label={`${c.name}音色`} placeholder="音色 ID，空白使用默认" value={c.voice} onChange={e => setCharacters(old => old.map(x => x.id === c.id ? { ...x, voice: e.target.value } : x))} onBlur={e => void updateCharacter(c, { voice: e.target.value })} /></div>) : <p className="muted small">导入 NPC 后或自动识别到人物台词后，这里会显示可朗读人物。</p>}</div>
      </>}
    </section>
    {message && <p className="drawer-message" role="status">{message}</p>}
    <div className="drawer-actions"><button type="button" className="primary" disabled={busy} onClick={() => void save()}>保存全部模型与语音设置</button><button type="button" className="ghost" disabled={busy} onClick={() => { setBusy(true); resetSettings().then(async d => { load(d); window.dispatchEvent(new Event('rpg-settings-changed')); await onChanged(); setMessage('已恢复脚本演示，语音已关闭。'); }).catch(e => setMessage(String(e))).finally(() => setBusy(false)); }}>恢复默认</button></div>
  </section>;
}
