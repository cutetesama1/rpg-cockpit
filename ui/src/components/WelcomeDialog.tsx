import { useEffect, useState } from "react";

const AGE_KEY = "rpg-age-ack";
const WELCOME_KEY = "rpg-welcome-seen";

interface WelcomeDialogProps {
  open: boolean;
  onClose: () => void;
  onOpenSettings: () => void;
}

/** 首次进入：年龄提示 + 上手引导。提示是提示，不拦截任何玩法。 */
export default function WelcomeDialog({
  open,
  onClose,
  onOpenSettings,
}: WelcomeDialogProps) {
  const [step, setStep] = useState<"age" | "guide">("age");

  useEffect(() => {
    if (!open) return;
    setStep(localStorage.getItem(AGE_KEY) ? "guide" : "age");
  }, [open]);

  if (!open) return null;

  function finish() {
    localStorage.setItem(WELCOME_KEY, "1");
    onClose();
  }

  function acknowledge() {
    localStorage.setItem(AGE_KEY, "1");
    setStep("guide");
  }

  return (
    <div className="modal-mask" onClick={finish}>
      <div className="modal welcome-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>{step === "age" ? "开始之前" : "怎么玩"}</h2>
            <p className="modal-sub">叙事驾驶舱 · 单机叙事游戏</p>
          </div>
          <button className="ghost" onClick={finish} title="关闭（随时可从左侧菜单重看）">✕</button>
        </div>

        {step === "age" ? (
          <div className="welcome-body">
            <p>
              本作品为<strong>虚构叙事</strong>，题材包含悬疑与轻微惊悚元素，请自行判断是否适合自己；
              本作<strong>不面向未成年人</strong>。
            </p>
            <p className="hint">
              这只是提示，不是限制：没有强制年龄验证，也不限制任何行动、回合或结局——你可以随时暂停、存档、
              读档或离开。
            </p>
            <div className="modal-actions">
              <button className="ghost" onClick={finish}>先随便看看</button>
              <button className="primary" onClick={acknowledge}>我已了解，继续</button>
            </div>
          </div>
        ) : (
          <div className="welcome-body">
            <ol className="welcome-steps">
              <li>
                <strong>先用叙事模型启动本局</strong>：在「设置」里选一个 OpenAI 兼容服务（填地址、模型名、Key），
                或已有的本地模型服务。不设置模型也可以浏览界面、看内容包、存档读档。
              </li>
              <li>
                <strong>自由行动</strong>：在「你的行动」里用自己的话写任何事；也可以点下面的作者建议标签。
                Enter 发送、Shift+Enter 换行。
              </li>
              <li>
                <strong>左侧菜单是全部入口</strong>：游戏库（多游戏/新游戏/复制）、世界构筑（世界书/技能/提示词）、
                存档读档、设置、撤销与重开。
              </li>
              <li>
                <strong>结局只是标记</strong>：看到结局后仍能继续行动、回到其他场景或继续当班；存档可以随时读回去，
                不会锁死任何内容。
              </li>
            </ol>
            <div className="modal-actions">
              <button
                className="ghost"
                onClick={() => {
                  finish();
                  onOpenSettings();
                }}
              >
                去设置模型
              </button>
              <button className="primary" onClick={finish}>开始游戏</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function welcomeSeen(): boolean {
  return localStorage.getItem(WELCOME_KEY) === "1";
}
