"""Verify generated UI art in desktop/mobile layouts with an offline preview fixture."""
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
        await call("Page.enable");await call("Runtime.enable");await call("Network.enable")
        await call("Network.setCacheDisabled",{"cacheDisabled":True})
        await call("Emulation.setDeviceMetricsOverride",{"width":1440,"height":1040,"deviceScaleFactor":1,"mobile":False})
        seed=await call("Page.addScriptToEvaluateOnNewDocument",{"source":"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.removeItem('rpg-theme');localStorage.setItem('rpg-nav-collapsed','0')"})
        await call("Page.navigate",{"url":BASE+"/?skipDisclaimer=1"})
        await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        await call("Page.removeScriptToEvaluateOnNewDocument",{"identifier":seed["identifier"]})
        await wait("Array.from(document.images).filter(i=>i.src.includes('/art/')).every(i=>i.complete&&i.naturalWidth>0)")
        await js("document.fonts.ready")
        # Wait for CSS background assets too, before capturing a useful preview.
        art=await js("Promise.all(['night-background','portrait-alcove','compass-crest'].map(name=>new Promise(resolve=>{const i=new Image();i.onload=()=>resolve({name,width:i.naturalWidth,height:i.naturalHeight});i.onerror=()=>resolve({name,error:true});i.src='/art/ui-v1/'+name+'.png'})))")
        assert all('error' not in row for row in art),art
        assert await js("document.querySelector('.app').classList.contains('has-wallpaper')")
        assert 'portrait-alcove' in await js("getComputedStyle(document.querySelector('.sprite-stage')).backgroundImage")
        def layout_script(): return "({viewport:innerWidth,page:document.documentElement.scrollWidth,textFont:getComputedStyle(document.querySelector('.story-entry p')).fontSize,textColor:getComputedStyle(document.querySelector('.story-entry p')).color,stageBackground:getComputedStyle(document.querySelector('.sprite-stage')).backgroundImage})"
        checks=[]
        checks.append({'mode':'desktop',**(await js(layout_script()))})
        assert checks[-1]['page']<=1441,checks[-1]
        await screenshot('p15-desktop')
        # Existing stored plain/custom wallpaper choices must remain respected.
        await js("localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'none',fontScale:100,spriteAnimated:false}))")
        await call('Page.reload');await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        assert not await js("document.querySelector('.app').classList.contains('has-wallpaper')")
        await js("localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'observatory',fontScale:100,spriteAnimated:false}))")
        await call('Page.reload');await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
        await js("window.scrollTo(0,0)")
        await wait("document.querySelector('.sidebar').getBoundingClientRect().right<=0")
        checks.append({'mode':'mobile',**(await js(layout_script()))})
        assert checks[-1]['page']<=391,checks[-1]
        await screenshot('p15-mobile')
        await js("document.querySelector('[aria-label=\"打开导航菜单\"]').click()")
        await wait("Boolean(document.querySelector('.nav-open'))")
        await screenshot('p15-mobile-nav')
        await js("Array.from(document.querySelectorAll('.sidebar button')).find(b=>b.textContent.trim()==='设置').click()")
        await wait("Boolean(document.querySelector('.drawer'))")
        await wait("document.querySelectorAll('.wallpaper-swatch').length>=7")
        await js("Array.from(document.querySelectorAll('.wallpaper-swatch')).find(b=>b.title==='星穹庭院').scrollIntoView({block:'center'})")
        await screenshot('p15-mobile-wallpaper-settings')
        await click('纯深色')
        await wait("!document.querySelector('.app').classList.contains('has-wallpaper')")
        await click('星穹庭院')
        await wait("document.querySelector('.app').classList.contains('has-wallpaper')")
        await click('关闭')
        for scale in (50,160):
            await js(f"localStorage.setItem('rpg-theme',JSON.stringify({{wallpaper:'observatory',fontScale:{scale},fontTarget:'all',spriteAnimated:false}}))")
            await call('Page.reload');await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
            check={'mode':f'mobile_font_{scale}',**(await js(layout_script()))}
            checks.append(check);assert check['page']<=391,check
        await js("localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'observatory',fontScale:100,fontTarget:'narrative',spriteAnimated:false}))")
        await call('Page.reload');await wait("Boolean(document.querySelector('.column.right .sprite-panel.ready'))")
        await call("Emulation.setDeviceMetricsOverride",{"width":844,"height":390,"deviceScaleFactor":1,"mobile":True})
        check={'mode':'landscape',**(await js(layout_script()))};checks.append(check);assert check['page']<=845,check
        await js("document.activeElement?.blur();window.scrollTo(0,0)")
        await wait("document.querySelector('.gamebar').getBoundingClientRect().top>=0")
        assert await js("document.querySelector('.column.right .sprite-stage').getBoundingClientRect().bottom<=innerHeight")
        await screenshot('p15-mobile-landscape')
        assert not errors,errors
        assert not bad,bad
        report={'art':art,'layouts':checks,'existing_plain_theme_preserved':True,'wallpaper_picker_works':True,'mobile_navigation_works':True,'errors':errors,'bad_responses':bad}
        (ROOT/'docs/previews/p15-art-browser-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
