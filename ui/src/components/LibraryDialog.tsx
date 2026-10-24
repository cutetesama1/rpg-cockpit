import PersonalityNpcPanel from "./PersonalityNpcPanel";
import CharacterCardImporter from "./CharacterCardImporter";
import { useEffect, useState } from "react";
import { cloneGame, getLibrary, newGame, selectGame } from "../api";
import type { GameInfo, LibraryView } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 切换/新建游戏后刷新主界面状态。 */
  onGameChanged: () => void;
  /** 直接打开当前游戏的世界构筑。 */
  onOpenWorld: () => void;
  /** 打开「快速创建世界」对话框。 */
  onOpenQuickCreate: () => void;
}

function countLabel(game: GameInfo): string {
  return `世界书 ${game.worldbook_entries} · 技能 ${game.skills} · 场景 ${game.scenes}`;
}

export default function LibraryDialog({
  open,
  onClose,
  onGameChanged,
  onOpenWorld,
  onOpenQuickCreate,
}: Props) {
  const [library, setLibrary] = useState<LibraryView | null>(null);
  const [mode, setMode] = useState<"new" | "clone" | null>(null);
  const [source, setSource] = useState<GameInfo | null>(null);
  const [title, setTitle] = useState("");
  const [gameId, setGameId] = useState("");
  const [busy, setBusy] = useState(false);
  const [cardOpen,setCardOpen]=useState(false);
  const [cardMode,setCardMode]=useState("full");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setLibrary(await getLibrary());
    } catch (err) {
      setError(String(err));
    }
  };

  useEffect(() => {
    if (!open) return;
    setMode(null);
    setCardOpen(false);
    setSource(null);
    setTitle("");
    setGameId("");
    setMessage(null);
    setError(null);
    void load();
  }, [open]);

  if (!open) return null;

  const start = async (game: GameInfo) => {
    setBusy(true);
    setError(null);
    try {
      const view = await selectGame(game.id);
      setLibrary(view);
      setMessage(`已进入「${game.title}」，状态已重置到开场。`);
      onGameChanged();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const beginNew = () => {
    setMode("new");
    setSource(null);
    setTitle("");
    setGameId("");
    setError(null);
    setMessage(null);
  };

  const beginClone = (game: GameInfo) => {
    setMode("clone");
    setSource(game);
    setTitle(`${game.title} 副本`);
    setGameId("");
    setError(null);
    setMessage(null);
  };

  const submit = async () => {
    if (!title.trim()) {
      setError("请填写游戏标题");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const view =
        mode === "clone" && source
          ? await cloneGame(source.id, title.trim(), gameId.trim() || undefined)
          : await newGame(title.trim(), gameId.trim() || undefined);
      setLibrary(view);
      setMessage(`已创建并进入「${title.trim()}」。`);
      setMode(null);
      onGameChanged();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-mask" role="dialog" aria-modal="true">
      <div className="modal library-modal">
        <header className="modal-head">
          <h2>游戏库</h2>
          <button className="ghost" onClick={onClose}>
            关闭
          </button>
        </header>

        <div className="modal-toolbar">
          <button className="ghost" onClick={()=>setCardOpen(value=>!value)} disabled={busy}>{cardOpen?"收起角色卡导入":"导入角色卡 V2/V3"}</button>
          <button className="primary" onClick={beginNew} disabled={busy}>
            新建游戏
          </button>
          <button className="ghost" onClick={() => void load()} disabled={busy}>
            刷新
          </button>
          <button
            className="primary"
            title="把一段素材交给 AI，自动拆成提示词 + 世界书 + 技能并建成新游戏"
            onClick={onOpenQuickCreate}
            disabled={busy}
          >
            ✨ AI 快速创建
          </button>
          <button className="ghost" onClick={onOpenWorld} disabled={busy}>
            当前游戏的世界构筑
          </button>
        </div>

        {cardOpen && <><label>角色卡导入模式<select aria-label="角色卡导入模式" value={cardMode} onChange={e=>setCardMode(e.target.value)}><option value="full">完整映射 · 创建新游戏</option><option value="personality">仅人格 · 多选加入当前世界 NPC</option></select></label>{cardMode==="full"?<CharacterCardImporter onCreated={()=>{onGameChanged();void load();}}/>:<PersonalityNpcPanel onChanged={()=>{onGameChanged();void load();}}/>}</>}

        {message && <p className="modal-message ok">{message}</p>}
        {error && <p className="modal-message bad">{error}</p>}

        {mode && (
          <section className="modal-form">
            <h3>{mode === "clone" ? `复制「${source?.title}」为新游戏` : "新建游戏"}</h3>
            <label>
              标题
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：雨夜书店"
                autoFocus
              />
            </label>
            <label>
              游戏 id（可留空自动生成）
              <input
                value={gameId}
                onChange={(event) => setGameId(event.target.value)}
                placeholder="例如：rainy-bookstore"
              />
            </label>
            <p className="hint">
              新游戏会创建在用户目录里，自带最小可玩内容：一个状态字段、一个查看技能、一个开场场景与金样测试。
              {mode === "clone" ? " 复制会带上原包的全部世界书、技能、场景与提示词。" : ""}
            </p>
            <div className="modal-actions">
              <button className="primary" onClick={() => void submit()} disabled={busy}>
                创建并进入
              </button>
              <button className="ghost" onClick={() => setMode(null)} disabled={busy}>
                取消
              </button>
            </div>
          </section>
        )}

        <div className="game-list">
          {(library?.packs ?? []).map((game) => (
            <article
              className={`game-card${game.active ? " active" : ""}${game.valid ? "" : " broken"}`}
              key={game.id}
            >
              <div className="game-card-head">
                <div>
                  <h3>{game.title}</h3>
                  <p className="game-id">
                    {game.id}
                    {game.version ? ` · v${game.version}` : ""}
                    {game.rating ? ` · ${game.rating}` : ""}
                  </p>
                </div>
                <div className="game-badges">
                  {game.active && <span className="badge active">当前</span>}
                  <span className="badge">{game.builtin ? "内置" : "我的"}</span>
                  {game.builtin ? (
                    <span className="badge muted">只读</span>
                  ) : (
                    <span className="badge ok">可编辑</span>
                  )}
                </div>
              </div>
              {game.description && <p className="game-desc">{game.description}</p>}
              {game.valid ? (
                <p className="game-meta">{countLabel(game)}</p>
              ) : (
                <p className="modal-message bad">无法加载：{game.error}</p>
              )}
              <div className="game-actions">
                <button
                  className="primary"
                  onClick={() => void start(game)}
                  disabled={busy || !game.valid || game.active}
                >
                  {game.active ? "正在玩" : "开始玩"}
                </button>
                {game.builtin && (
                  <button className="ghost" onClick={() => beginClone(game)} disabled={busy}>
                    复制为新游戏
                  </button>
                )}
                {!game.builtin && !game.active && (
                  <button className="ghost" onClick={() => void start(game)} disabled={busy}>
                    切到这个世界
                  </button>
                )}
              </div>
            </article>
          ))}
          {library && library.packs.length === 0 && (
            <p className="empty">还没有任何游戏，点「新建游戏」开始。</p>
          )}
        </div>

        <footer className="modal-foot">
          <span>内置：{library?.builtin_dir ?? ""}</span>
          <span>我的游戏：{library?.user_dir ?? ""}</span>
        </footer>
      </div>
    </div>
  );
}
