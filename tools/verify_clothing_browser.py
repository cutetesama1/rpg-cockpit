"""Drive actual action submissions and verify post-narrative clothing state/pixels."""
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
        async def click(text):
            await js(f"Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==={json.dumps(text)}).click()")
        def state(): return json.load(urllib.request.urlopen(BASE+'/api/state'))['state']
        await call("Page.enable");await call("Runtime.enable");await call("Network.enable")
        await call("Network.setCacheDisabled",{"cacheDisabled":True})
        await call("Emulation.setDeviceMetricsOverride",{"width":1400,"height":1000,"deviceScaleFactor":1,"mobile":False})
        await call("Page.addScriptToEvaluateOnNewDocument",{"source":"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({spriteAnimated:false,showSprite:true,spriteView:'full'}))"})
        await call("Page.navigate",{"url":BASE+'/?skipDisclaimer=1'})
        await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        previous=await pixels('.column.right .sprite-canvas')
        checks=[];images=[]
        expected=[('hoodie','trousers','intact',True),('hoodie','trousers','damaged',True),('hoodie','trousers','damaged',False),('hoodie','trousers','damaged',False),('hoodie','trousers','intact',True),('sweater','jeans','intact',True)]
        for index,(upper,lower,condition,changed) in enumerate(expected,1):
            await js("(()=>{const t=document.querySelector('.action-dock textarea');t.focus();t.select()})()")
            await call("Input.insertText",{"text":"继续训练"})
            await wait("Array.from(document.querySelectorAll('button')).some(b=>b.textContent.trim()==='发送'&&!b.disabled)")
            await click('发送')
            await wait(f"document.querySelectorAll('.story-entry').length==={index+1}")
            await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
            await asyncio.sleep(.2)
            current=await pixels('.column.right .sprite-canvas')
            current_state=state()
            assert (current_state['upper'],current_state['lower'],current_state['upper_condition'])==(upper,lower,condition),current_state
            assert (current!=previous)==changed,(index,'wrong pixel change')
            badges=await js("document.querySelector('.column.right .clothing-condition-row').textContent")
            assert ('破损' in badges)==(condition=='damaged'),badges
            if index in (1,2,5,6):
                (ROOT/f'docs/previews/p14-browser-turn-{index}.png').write_bytes(current)
            checks.append({'turn':index,'upper':upper,'lower':lower,'condition':condition,'pixels_changed':current!=previous,'sha256':hashlib.sha256(current).hexdigest()})
            images.append(current);previous=current
        assert images[0]==images[4],'Repair did not restore the original garment pixels'
        report={'test_kind':'recorded_real_model_output_replay_through_real_form_and_sse','checks':checks,'repair_restores_pixels':True,'errors':errors,'bad_assets':bad}
        assert not errors,errors
        assert not bad,bad
        (ROOT/'docs/previews/p14-clothing-browser-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        image=await call('Page.captureScreenshot',{'format':'png'})
        (ROOT/'docs/previews/p14-browser.png').write_bytes(base64.b64decode(image['data']))
        print(json.dumps({'turns':len(checks),'repair_restores_pixels':True,'errors':len(errors),'bad_assets':len(bad)}))

if __name__=='__main__':asyncio.run(main())
