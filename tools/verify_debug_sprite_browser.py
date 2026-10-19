"""Drive the actual debug form; check draft preview and applied scene pixels."""
import asyncio, base64, hashlib, json, urllib.request
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18812"

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
                    if "/api/pack/asset/" in r["url"] and r["status"]>=400: bad.append(r["url"])
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
        async def pixels(selector):
            data=await js(f"document.querySelector({json.dumps(selector)}).toDataURL()")
            return base64.b64decode(data.split(",",1)[1])
        async def select(field,value):
            selector=f'.debug-console [data-field-id="{field}"] select'
            await js(f"(()=>{{const input=document.querySelector({json.dumps(selector)}); input.value={json.dumps(value)}; input.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
            await wait("Boolean(document.querySelector('.dbg-sprite-preview .sprite-panel.ready'))")
            await asyncio.sleep(.2)
        async def click(text):
            await js(f"Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==={json.dumps(text)}).click()")
        def state(): return json.load(urllib.request.urlopen(BASE+'/api/state'))['state']
        await call("Page.enable");await call("Runtime.enable");await call("Network.enable")
        await call("Network.setCacheDisabled",{"cacheDisabled":True})
        await call("Emulation.setDeviceMetricsOverride",{"width":1400,"height":1000,"deviceScaleFactor":1,"mobile":False})
        await call("Page.addScriptToEvaluateOnNewDocument",{"source":"localStorage.setItem('rpg-theme',JSON.stringify({spriteAnimated:false,showSprite:true,spriteView:'full'}))"})
        await call("Page.navigate",{"url":BASE+'/?skipDisclaimer=1'})
        await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        await js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('调试台')).click()")
        await click('立绘/外观')
        await wait("Boolean(document.querySelector('.dbg-sprite-preview .sprite-panel.ready'))")
        checks=[]
        for garment in ['hoodie','sweater','babydoll','tshirt']:
            before=state()['upper']
            scene_before=await pixels('.column.right .sprite-canvas')
            await select('upper',garment)
            assert state()['upper']==before,'A draft unexpectedly wrote state'
            preview=await pixels('.dbg-sprite-preview .sprite-canvas')
            assert preview!=scene_before,(garment,'draft preview did not change')
            await click('保存并应用外观')
            await wait("!document.querySelector('.debug-console').textContent.includes('尚未保存到游戏')")
            await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
            await asyncio.sleep(.25)
            scene=await pixels('.column.right .sprite-canvas')
            assert state()['upper']==garment,(garment,'state did not update')
            assert scene==preview,(garment,'saved scene differs from draft preview')
            assert scene!=scene_before,(garment,'scene did not change after apply')
            (ROOT/f'docs/previews/p12-debug-applied-{garment}.png').write_bytes(scene)
            checks.append({'upper':garment,'state':garment,'pixels_changed':True,'matches_preview':True,'sha256':hashlib.sha256(scene).hexdigest()})
        for hairstyle in ['aerial','french curls','bedhead']:
            await select('hair_style',hairstyle)
            await click('保存并应用外观')
            await asyncio.sleep(.4)
            assert state()['hair_style']==hairstyle
            (ROOT/f'docs/previews/p12-debug-hair-{hairstyle.replace(" ","-")}.png').write_bytes(await pixels('.column.right .sprite-canvas'))
        await js("document.querySelector('.dbg-sprite-preview').scrollIntoView({block:'center'})")
        image=await call('Page.captureScreenshot',{'format':'png'})
        (ROOT/'docs/previews/p12-debug-browser.png').write_bytes(base64.b64decode(image['data']))
        assert not errors,errors
        assert not bad,bad
        report={'clothes':checks,'hair':['aerial','french curls','bedhead'],'errors':errors,'bad_assets':bad}
        (ROOT/'docs/previews/p12-debug-browser-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'clothing_changes':len(checks),'hair_changes':3,'errors':len(errors),'bad_assets':len(bad)}))

if __name__=='__main__':asyncio.run(main())
