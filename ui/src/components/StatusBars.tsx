import type { FieldDef, Layout, NarratorStatus, Scalar } from "../types";

interface Props {
  fields: FieldDef[];
  state: Record<string, Scalar>;
  layout: Layout;
  /** 最近一次叙述附带的角色状态（姓名 + 四项 0~100 评分）。 */
  narrativeStatus?: NarratorStatus | null;
  /** 勾选技能本回合预扣的数值（field id → 正数总量）。 */
  preview?: Record<string, number>;
}

const PALETTE = ["#34d399", "#38bdf8", "#a855f7", "#f59e0b", "#f87171", "#2dd4bf"];

const NARRATIVE_METERS: { key: "lewd" | "body" | "sensitivity" | "desire"; label: string; color: string }[] = [
  { key: "lewd", label: "色情程度", color: "#f472b6" },
  { key: "body", label: "小穴与身体", color: "#a855f7" },
  { key: "sensitivity", label: "敏感度", color: "#f59e0b" },
  { key: "desire", label: "倾向", color: "#38bdf8" },
];

function score(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function percent(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
}

function fieldColor(field: FieldDef, index: number): string {
  const color = field.color?.trim();
  if (color && /^#[0-9a-fA-F]{6}$/.test(color)) return color;
  return PALETTE[index % PALETTE.length];
}

export default function StatusBars({
  fields,
  state,
  layout,
  narrativeStatus,
  preview,
}: Props) {
  const byId = new Map(fields.map((field) => [field.id, field]));
  const bars = layout.bars
    .map((id) => byId.get(id))
    .filter((field): field is FieldDef => Boolean(field));
  const numbers = layout.numbers
    .map((id) => byId.get(id))
    .filter((field): field is FieldDef => Boolean(field));
  const badges = layout.badges
    .map((id) => byId.get(id))
    .filter((field): field is FieldDef => Boolean(field));
  const costOf = (id: string) => Math.max(0, Number(preview?.[id] ?? 0));
  const hasPreview = Object.values(preview ?? {}).some((amount) => Number(amount) > 0);

  return (
    <section className="panel panel-compact">
      <h2>
        状态
        {hasPreview && (
          <span className="preview-tag" title="勾选的技能会在本次发送时一起结算">
            技能预扣
          </span>
        )}
      </h2>
      {bars.map((field, index) => {
        const value = Number(state[field.id] ?? 0);
        const min = field.min ?? 0;
        const max = field.max ?? Math.max(value, 1);
        const cost = costOf(field.id);
        const after = Math.max(0, value - cost);
        const pct = percent(cost > 0 ? after : value, min, max);
        const beforePct = percent(value, min, max);
        const low = pct <= 25;
        const short = cost > 0 && value - cost < 0;
        const color = fieldColor(field, index);
        return (
          <div
            className={`bar-row${cost > 0 ? " bar-row-preview" : ""}${short ? " bar-row-short" : ""}`}
            key={field.id}
            title={
              cost > 0
                ? `${field.label}：${value} → ${after}（勾选技能本回合合计消耗 ${cost}）${short ? " · 数值不足" : ""}`
                : field.label
            }
          >
            <span className="bar-label">
              {field.label}
              {cost > 0 && <i className="bar-cost">−{cost}</i>}
            </span>
            <div className="bar-track">
              <div
                className={`bar-fill ${low ? "bar-fill-low" : ""}`}
                style={{
                  width: `${pct}%`,
                  background: low
                    ? "linear-gradient(90deg, #b91c1c, #f87171)"
                    : `linear-gradient(90deg, ${color}, ${color}b3)`,
                }}
              />
              {cost > 0 && beforePct > pct && (
                <div
                  className="bar-cost-range"
                  style={{
                    left: `${pct}%`,
                    width: `${beforePct - pct}%`,
                    backgroundImage: `repeating-linear-gradient(45deg, ${color}, ${color} 4px, #0a0d11 4px, #0a0d11 8px)`,
                  }}
                />
              )}
            </div>
            <span
              className={`bar-value${cost > 0 ? " bar-value-preview" : ""}${short ? " bar-value-short" : ""}`}
            >
              {cost > 0 ? (
                <>
                  {value}
                  <em>→{after}</em>
                </>
              ) : (
                <>
                  {value}
                  <small>/{max}</small>
                </>
              )}
            </span>
          </div>
        );
      })}

      {numbers.length > 0 && (
        <div className="numbers">
          {numbers.map((field, index) => {
            const value = Number(state[field.id] ?? 0);
            const cost = costOf(field.id);
            const after = Math.max(0, value - cost);
            return (
              <div
                className={`number-chip${cost > 0 ? " number-chip-preview" : ""}`}
                key={field.id}
                title={cost > 0 ? `${field.label}：${value} → ${after}（预扣 ${cost}）` : field.label}
              >
                <i
                  className="number-dot"
                  style={{ background: fieldColor(field, bars.length + index) }}
                />
                <span>{field.label}</span>
                <strong>
                  {String(value)}
                  {field.unit ?? ""}
                  {cost > 0 && (
                    <em>
                      →{after}
                      {field.unit ?? ""}
                    </em>
                  )}
                </strong>
              </div>
            );
          })}
        </div>
      )}

      {badges.length > 0 && (
        <div className="badges">
          {badges.map((field) => (
            <span
              className={`badge ${state[field.id] ? "badge-on" : ""}`}
              key={field.id}
            >
              {field.label}
            </span>
          ))}
        </div>
      )}

      {narrativeStatus && (
        <div className="narrative-status">
          <div className="narrative-name" title="叙事模型记录的主角姓名">
            <span>{narrativeStatus.name?.trim() || "姓名未记录"}</span>
            <small>角色状态</small>
          </div>
          {NARRATIVE_METERS.map((meter) => {
            const value = score(narrativeStatus[meter.key]);
            const note = narrativeStatus.notes?.[meter.key]?.trim();
            return (
              <div className="narrative-item" key={meter.key}>
                <div
                  className="narrative-row"
                  title={`${meter.label}：${value}/100（由叙事模型评分）`}
                >
                  <span className="narrative-label">{meter.label}</span>
                  <div className="narrative-track">
                    <div
                      className="narrative-fill"
                      style={{ width: `${value}%`, background: meter.color }}
                    />
                  </div>
                  <span className="narrative-value">{value}</span>
                </div>
                {note ? (
                  <p className="narrative-note" title={note}>
                    {note}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {hasPreview && (
        <p className="preview-note">
          斜纹部分为勾选技能的预扣，发送时一起结算；取消勾选即恢复。
        </p>
      )}
    </section>
  );
}
