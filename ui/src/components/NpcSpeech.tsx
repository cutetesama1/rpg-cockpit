import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ChatEntry } from "../chatHistory";
import type { VoiceDialogue, VoiceLine, VoiceView } from "../types";

let snapshot: VoiceView | null = null;
let pending: Promise<void> | null = null;
const listeners = new Set<() => void>();
let activeStop: (() => void) | null = null;
function refreshVoice() {
  if (pending) return pending;
  pending = fetch('/api/voice').then(async r => {
    if (!r.ok) throw new Error('无法读取语音设置');
    snapshot = await r.json() as VoiceView;
    listeners.forEach(fn => fn());
  }).catch(() => { snapshot = null; listeners.forEach(fn => fn()); }).finally(() => { pending = null; });
  return pending;
}
window.addEventListener('rpg-settings-changed', () => { activeStop?.(); void refreshVoice(); });
window.addEventListener('rpg-voice-characters-changed', () => { activeStop?.(); void refreshVoice(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) activeStop?.(); });
function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
async function readError(r: Response) { const data = await r.json().catch(() => ({})); return new Error(typeof data.detail === 'string' ? data.detail : `语音请求失败 (${r.status})`); }

export default function NpcSpeech({ entry, packId, automatic = false }: { entry: ChatEntry; packId: string; automatic?: boolean }) {
  const view = useSyncExternalStore(subscribe, () => snapshot);
  const [dialogue, setDialogue] = useState<VoiceDialogue | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [source, setSource] = useState('');
  const audio = useRef<HTMLAudioElement>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const objectUrl = useRef('');
  const finish = useRef<(() => void) | null>(null);
  const enabled = view?.pack_id === packId && view.speech.enabled;
  const eligible = !entry.streaming && !entry.failed && entry.role === 'assistant' && /^(?:ai-|correction-ai-)/.test(entry.id);
  const stop = () => {
    generation.current++; request.current?.abort(); request.current = null;
    audio.current?.pause(); finish.current?.(); finish.current = null;
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = ''; setSource(''); setPlaying(false); setWorking(false);
    if (activeStop === stop) activeStop = null;
  };
  useEffect(() => { if (snapshot?.pack_id !== packId) void refreshVoice(); return () => { activeStop?.(); }; }, [packId]);
  useEffect(() => () => { generation.current++; request.current?.abort(); audio.current?.pause(); finish.current?.(); if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, [entry.id, packId]);
  const identify = async (signal?: AbortSignal) => {
    const r = await fetch('/api/voice/dialogue', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pack_id: packId, entry_id: entry.id }), signal });
    if (!r.ok) throw await readError(r);
    const data = await r.json() as VoiceDialogue;
    if (snapshot?.pack_id === packId) { snapshot = { ...snapshot, characters: data.characters }; listeners.forEach(fn => fn()); }
    setDialogue(data); return data;
  };
  useEffect(() => {
    setDialogue(null); setError('');
    if (!enabled || !eligible || !automatic) return;
    const controller = new AbortController();
    setWorking(true);
    identify(controller.signal).catch(e => { if (!controller.signal.aborted) setError(String(e)); }).finally(() => { if (!controller.signal.aborted) setWorking(false); });
    return () => controller.abort();
  }, [enabled, eligible, automatic, entry.id, packId, view?.speech.mode]);
  if (!enabled || !eligible) return null;
  const play = async (line?: VoiceLine) => {
    activeStop?.(); stop(); activeStop = stop;
    const serial = generation.current;
    const controller = new AbortController(); request.current = controller;
    setWorking(true); setError('');
    try {
      const data = await identify(controller.signal);
      if (serial !== generation.current) return;
      const lines = data.lines.filter(l => l.enabled && (!line || l.id === line.id));
      if (!lines.length) { setError('没有可朗读的 NPC 台词，或该人物朗读已关闭。'); return; }
      setPlaying(true);
      for (const item of lines) {
        if (serial !== generation.current) break;
        setWorking(true);
        const r = await fetch('/api/voice/audio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
          body: JSON.stringify({ pack_id: packId, entry_id: entry.id, revision: data.revision, line_id: item.id }) });
        if (!r.ok) throw await readError(r);
        const blob = await r.blob();
        if (serial !== generation.current) break;
        if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
        const url = URL.createObjectURL(blob); objectUrl.current = url; setSource(url); setWorking(false);
        const element = audio.current;
        if (!element) break;
        element.src = url;
        await new Promise<void>((resolve, reject) => {
          finish.current = resolve;
          element.onended = () => resolve();
          element.onerror = () => reject(new Error('当前设备无法播放该音频格式'));
          element.play().catch(() => { setError('浏览器需要播放确认，请点击下方音频播放键。'); });
        });
      }
    } catch (e) { if (!controller.signal.aborted) setError(String(e)); }
    finally { if (serial === generation.current) { setWorking(false); setPlaying(false); if (activeStop === stop) activeStop = null; } }
  };
  return <section className="npc-speech" aria-label="NPC 台词语音">
    <div className="npc-speech-toolbar"><button type="button" className="ghost small" disabled={working || playing} onClick={() => void play()}>◖)) {working ? '识别 / 生成中…' : '听 NPC 台词'}</button>{(working || playing) && <button type="button" className="ghost small" onClick={stop}>■ 停止</button>}</div>
    {dialogue && <details><summary>{dialogue.lines.length ? `${dialogue.lines.length} 句 NPC 台词 · 可单句播放` : '本段未识别到可朗读 NPC 台词'}</summary>{dialogue.lines.map(line => <div className="npc-speech-line" key={line.id}><strong>{line.name}</strong><span>{line.text}</span><button type="button" className="ghost small" disabled={working || playing || !line.enabled} onClick={() => void play(line)}>{line.enabled ? '▶ 播放' : '已关闭'}</button></div>)}</details>}
    <audio ref={audio} controls style={{ display: source ? 'block' : 'none' }} aria-label="NPC 语音播放器" />
    {error && <p className="muted small" role="status">{error}</p>}
  </section>;
}
