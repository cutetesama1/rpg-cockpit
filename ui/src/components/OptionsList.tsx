import type { Option } from "../types";

interface Props {
  title: string;
  options: Option[];
  busy: boolean;
  /** 点击建议只把文本填入输入框，由玩家自己决定是否发送。 */
  onPick: (option: Option) => void;
}

export default function OptionsList({ title, options, busy, onPick }: Props) {
  if (options.length === 0) return null;
  return (
    <div className="suggestions">
      <span className="suggestions-title">{title}（点击填入输入框）</span>
      <div className="suggestion-chips">
        {options.map((option) => (
          <button
            key={option.id}
            className="chip"
            type="button"
            disabled={busy}
            title="填入输入框，不会直接发送"
            onClick={() => onPick(option)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
