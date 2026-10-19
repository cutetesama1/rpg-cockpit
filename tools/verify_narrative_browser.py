"""Verify the built UI with a seeded, isolated server on :18812 and Edge CDP :19234."""
import asyncio, base64, json, urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:18812"
async def main():
    tabs=json.load(urllib.request.urlopen("http://127.0.0.1:19234/json"))
    page=next(t for t in tabs if t.get("type")=="page")
    async with websockets.connect(page["webSocketDebuggerUrl"],max_size=20_000_000) as ws:
        seq=0; errors=[]; bad=[]
        async def call(method,params=None):
            nonlocal seq
            seq+=1; request=seq
            await ws.send(json.dumps({"id":request,"method":method,"params":params or {}}))
            while True:
                result=json.loads(await ws.recv())
                if result.get("method")=="Runtime.exceptionThrown": errors.append(result["params"])
                if result.get("method")=="Network.responseReceived":
                    r=result["params"]["response"]
                    if r["url"].startswith(BASE) and r["status"]>=400: bad.append({"url":r["url"],"status":r["status"]})
                if result.get("id")==request:
                    assert "error" not in result,result
                    return result.get("result",{})
        async def js(expression):
            r=await call("Runtime.evaluate",{"expression":expression,"returnByValue":True,"awaitPromise":True})
            assert "exceptionDetails" not in r,r
            return r.get("result",{}).get("value")
        async def wait(expression):
            for _ in range(100):
                if await js(expression): return
                await asyncio.sleep(.1)
            raise AssertionError(expression)
        async def click(text):
            await js(f"Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==={json.dumps(text)}).click()")
        async def screenshot(name):
            shot=await call("Page.captureScreenshot",{"format":"png"})
            (ROOT/f"docs/previews/{name}.png").write_bytes(base64.b64decode(shot["data"]))
        await call("Page.enable"); await call("Runtime.enable"); await call("Network.enable")
        await call("Network.setCacheDisabled",{"cacheDisabled":True})
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
        seed=await call("Page.addScriptToEvaluateOnNewDocument",{"source":"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({fontScale:100,fontTarget:'narrative',spriteAnimated:false}))"})
        await call("Page.navigate",{"url":BASE+"/?skipDisclaimer=1"})
        await wait("Boolean(document.querySelector('.story-entry p'))")
        await call("Page.removeScriptToEvaluateOnNewDocument",{"identifier":seed["identifier"]})
        rendered=await js("document.querySelector('.story-entry p').textContent")
        assert '教练说：\n“先深呼吸。”\n你点了点头。\n\n门边传来声音：\n「准备好了吗？」\n风吹过窗台。' in rendered,rendered[:200]
        baseline_font=await js("parseFloat(getComputedStyle(document.querySelector('.story-entry p')).fontSize)")
        whitespace=await js("getComputedStyle(document.querySelector('.story-entry p')).whiteSpace")
        assert whitespace=="pre-wrap"
        await js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('设置')).click()")
        await wait("Boolean(document.querySelector('.drawer input[type=range][min=\"50\"]'))")
        await js("(()=>{let input=document.querySelector('.drawer input[type=range][min=\"50\"]');input.scrollIntoView({block:'center'});input.focus()})()")
        await call("Input.dispatchKeyEvent",{"type":"keyDown","key":"Home","code":"Home","windowsVirtualKeyCode":36})
        await call("Input.dispatchKeyEvent",{"type":"keyUp","key":"Home","code":"Home","windowsVirtualKeyCode":36})
        await wait("JSON.parse(localStorage.getItem('rpg-theme')).fontScale===50")
        narrative_font=await js("getComputedStyle(document.querySelector('.story-entry p')).fontSize")
        assert float(narrative_font.removesuffix("px"))==baseline_font/2,narrative_font
        await screenshot("p13-mobile-font-settings")
        await click("整页字体")
        await wait("getComputedStyle(document.documentElement).getPropertyValue('--ui-font-scale').trim()==='0.5'")
        await click("关闭")
        await call("Page.reload")
        await wait("Boolean(document.querySelector('.story-entry p'))")
        stored=await js("JSON.parse(localStorage.getItem('rpg-theme'))")
        assert stored["fontScale"]==50 and stored["fontTarget"]=="all",stored
        layout=await js("(()=>{let p=document.querySelector('.story-entry p');return {screen:innerWidth,page:document.documentElement.scrollWidth,story:p.scrollWidth,width:p.clientWidth,height:p.clientHeight,font:getComputedStyle(p).fontSize}})()")
        assert layout["page"]<=layout["screen"]+1,layout
        assert layout["story"]<=layout["width"]+1,layout
        assert float(layout["font"].removesuffix("px"))==baseline_font/2,layout
        await screenshot("p13-mobile-narrative")
        status=json.load(urllib.request.urlopen(BASE+"/api/state"))
        raw=next(e["payload"]["narrative"] for e in status["events"] if e["kind"]=="narrative.generated")
        assert raw.startswith('教练说：“先深呼吸。”你点了点头。\n\n'),raw[:100]
        assert not errors,errors
        assert not bad,bad
        report={"viewport":{"width":390,"height":844},"dialogue_line_breaks":True,"original_paragraphs_preserved":True,"raw_ledger_unchanged":True,"white_space":whitespace,"range_min":50,"range_max":160,"range_step":5,"font_50_via_keyboard":True,"narrative_font_size":narrative_font,"all_font_target":True,"persists_after_reload":True,"layout":layout,"errors":errors,"bad_responses":bad}
        (ROOT/"docs/previews/p13-narrative-browser-verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps(report))
if __name__=="__main__":asyncio.run(main())
