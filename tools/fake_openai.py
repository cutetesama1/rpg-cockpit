"""开发用的假 OpenAI 兼容端点：慢速（每次 1.2s）+ 固定工具调用，便于观察 SSE 流。

启动：python tools/fake_openai.py [port]（默认 8899）
然后在驾驶舱「模型设置」里填 base_url=http://127.0.0.1:8899/v1、model=fake-slow。
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY_SECONDS = float(os.environ.get("FAKE_DELAY", "1.2"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        time.sleep(DELAY_SECONDS)  # 模拟真实模型的延迟，让流式效果可见

        messages = body.get("messages", [])
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if not has_tool_result:
            # 第一轮：让模型"决定"扣血，走工具调用
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_fake_1",
                        "type": "function",
                        "function": {
                            "name": "damage",
                            "arguments": json.dumps(
                                {"field": "hp", "amount": 5, "reason": "假端点：影子撞了上来"}
                            ),
                        },
                    }
                ],
            }
        else:
            # 第二轮：工具结果回喂后输出叙事（禁止报数）
            content = {
                "narrative": "货架后面的影子晃了一下，你听见自己急促的呼吸声。",
                "options": [
                    {"id": "o1", "label": "继续", "action_text": "你握紧撬棍往前走"},
                    {"id": "o2", "label": "退后", "action_text": "你退向门口"},
                ],
            }
            message = {
                "role": "assistant",
                "content": json.dumps(content, ensure_ascii=False),
            }

        payload = {
            "id": "chatcmpl-fake",
            "model": body.get("model") or "fake-slow",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 60,
                "total_tokens": 180,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静默
        return None


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake OpenAI endpoint on http://127.0.0.1:{port}/v1 (delay {DELAY_SECONDS}s)")
    server.serve_forever()


if __name__ == "__main__":
    main()
