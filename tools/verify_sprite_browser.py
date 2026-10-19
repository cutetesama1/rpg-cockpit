"""Local Edge/CDP visual regression check, with an isolated test game session."""
import asyncio, base64, json, sys, urllib.request
from pathlib import Path
import websockets

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18812"

async def main():
    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:19234/json"))
    tab = next(t for t in tabs if t.get("type") == "page")
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        seq = 0
        errors, bad_assets = [], []
        async def call(method, params=None):
            nonlocal seq
            seq += 1
            request = seq
            await ws.send(json.dumps({"id": request, "method": method, "params": params or {}}))
            while True:
                event = json.loads(await ws.recv())
                if event.get("method") == "Runtime.exceptionThrown": errors.append(event["params"])
                if event.get("method") == "Network.responseReceived":
                    response = event["params"]["response"]
                    if "/api/pack/asset/" in response["url"] and response["status"] >= 400:
                        bad_assets.append(response["url"])
                if event.get("id") == request:
                    if "error" in event: raise RuntimeError(event["error"])
                    return event.get("result", {})
        async def evaluate(js):
            result = await call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
            if result.get("exceptionDetails"): raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")
        async def ready():
            for _ in range(100):
                if await evaluate("Boolean(document.querySelector('.sprite-panel.ready canvas'))"):
                    await asyncio.sleep(.15)
                    return
                await asyncio.sleep(.1)
            raise RuntimeError("Sprite did not become ready")
        async def screenshot(name, canvas=False):
            params = {"format": "png", "captureBeyondViewport": False}
            if canvas:
                clip = await evaluate("JSON.parse(JSON.stringify(document.querySelector('.sprite-canvas').getBoundingClientRect()))")
                params["clip"] = {k: clip[k] for k in ("x", "y", "width", "height")}
                params["clip"]["scale"] = 1
            result = await call("Page.captureScreenshot", params)
            (ROOT / "docs/previews" / name).write_bytes(base64.b64decode(result["data"]))
        await call("Page.enable")
        await call("Runtime.enable")
        await call("Network.enable")
        await call("Network.setCacheDisabled", {"cacheDisabled": True})
        await call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        report = []
        for view in ("full", "bust", "closeup_face", "closeup_mouth", "closeup_upper"):
            await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1&spriteView={view}"})
            await asyncio.sleep(.3)
            await ready()
            samples = []
            for _ in range(6):
                samples.append(await evaluate("({frame:window.__spriteFrame, width:document.querySelector('.sprite-canvas').width, height:document.querySelector('.sprite-canvas').height, pixels:Array.from(document.querySelector('.sprite-canvas').getContext('2d').getImageData(0,0,document.querySelector('.sprite-canvas').width,document.querySelector('.sprite-canvas').height).data).filter((x,i)=>i%4===3&&x>0).length})"))
                await asyncio.sleep(.2)
            assert all(s["pixels"] > 0 for s in samples), (view, samples)
            assert len({s["frame"] for s in samples}) > 1, (view, "animation frozen")
            # Capture an open/idle frame deterministically for visual review.
            for _ in range(15):
                if await evaluate("window.__spriteFrame === 0"): break
                await asyncio.sleep(.05)
            await screenshot(f"p11-browser-{view}.png")
            report.append({"view": view, "samples": samples})
        async def change(changes):
            req = urllib.request.Request(BASE + "/api/debug/state",
                  data=json.dumps({"changes": changes}).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as response:
                assert response.status == 200
        # Switch ordinary expressions in the isolated game and capture both idle frames.
        for expr in ("default", "aloof", "catty", "gloomy", "sweet"):
            await change({"expression": expr})
            await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1&spriteView=closeup_face"})
            await asyncio.sleep(.2)
            await ready()
            for frame in (0, 1):
                for _ in range(20):
                    if await evaluate(f"window.__spriteFrame === {frame}"): break
                    await asyncio.sleep(.05)
                await screenshot(f"p11-browser-{expr}-frame{frame}.png", canvas=True)
        # Check a restored half-resolution hairstyle and another eye colour.
        await change({"expression": "default", "hair_style": "bedhead", "eye_color": "blue"})
        await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1&spriteView=closeup_face"})
        await asyncio.sleep(.2)
        await ready()
        await screenshot("p11-browser-blue-bedhead.png", canvas=True)
        await change({"hair_style": "classic", "eye_color": "hazel"})
        # Unsupported legacy views must not fall back to a full-body portrait.
        await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1&spriteView=closeup_arse"})
        await asyncio.sleep(.4)
        await ready()
        empty = await evaluate("!document.querySelector('.sprite-canvas').getContext('2d').getImageData(0,0,424,380).data.some((v,i)=>i%4===3&&v)")
        assert empty, "Unsupported view leaked default layers"
        # The existing adult-only pose must remain empty with its toggle off.
        await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1&spriteView=closeup_chest"})
        await asyncio.sleep(.4)
        await ready()
        assert await evaluate("document.querySelector('.sprite-panel').textContent.includes('没有可显示')")
        await call("Page.navigate", {"url": f"{BASE}/?skipDisclaimer=1"})
        await asyncio.sleep(.2)
        await ready()
        await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('设置')).click()")
        await asyncio.sleep(.2)
        assert await evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='特写·面部')")
        await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='特写·面部').click()")
        await asyncio.sleep(.2)
        assert await evaluate("document.querySelector('.sprite-canvas').width === 160")
        await screenshot("p11-browser-settings.png")
        assert not bad_assets, bad_assets
        assert not errors, errors
        (ROOT / "docs/previews/p11-browser-verification.json").write_text(json.dumps({"views": report, "errors": errors, "bad_assets": bad_assets}, indent=2), encoding="utf-8")
        print(json.dumps({"views": [r["view"] for r in report], "errors": len(errors), "bad_assets": len(bad_assets)}))

if __name__ == "__main__": asyncio.run(main())
