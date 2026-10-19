"""Browser acceptance: actual model HTTP -> SSE -> incremental DOM and theme controls."""
import asyncio, base64, json, urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:18815"
async def main():
    for _ in range(80):
        try:
            if json.load(urllib.request.urlopen(BASE+'/api/health',timeout=1))['ok']:break
        except Exception:
            await asyncio.sleep(.1)
    page=json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:19235/json/new?about:blank",method="PUT")))
    async with websockets.connect(page["webSocketDebuggerUrl"],max_size=20_000_000) as ws:
        seq=0;errors=[];bad=[]
        async def call(method,params=None):
            nonlocal seq
            seq+=1;request=seq
            await ws.send(json.dumps({"id":request,"method":method,"params":params or {}}))
            while True:
                result=json.loads(await ws.recv())
                if result.get("method")=="Runtime.exceptionThrown":errors.append(result["params"])
                if result.get("method")=="Network.responseReceived":
                    r=result["params"]["response"]
                    if r["url"].startswith(BASE) and r["status"]>=400:bad.append({"url":r["url"],"status":r["status"]})
                if result.get("id")==request:
                    assert "error" not in result,result
                    return result.get("result",{})
        async def js(expr):
            result=await call("Runtime.evaluate",{"expression":expr,"returnByValue":True,"awaitPromise":True})
            assert "exceptionDetails" not in result,result
            return result.get("result",{}).get("value")
        async def wait(expr):
            for _ in range(160):
                if await js(expr):return
                await asyncio.sleep(.06)
            raise AssertionError(expr)
        async def shot(name):
            await asyncio.sleep(.23)  # Capture final colors after the normal button transition.
            result=await call("Page.captureScreenshot",{"format":"png"})
            (ROOT/f"docs/previews/{name}.png").write_bytes(base64.b64decode(result["data"]))
        async def set_input(selector,text):
            await js(f"(()=>{{let e=document.querySelector({json.dumps(selector)});Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,{json.dumps(text)});e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
        async def settings(phone=True):
            if phone:
                await js("document.querySelector('.chat-menu-button').click()")
                await wait("Boolean(document.querySelector('.mobile-settings-button'))")
                await js("document.querySelector('.mobile-settings-button').click()")
            else:
                await js("Array.from(document.querySelectorAll('.sidebar button')).find(b=>b.textContent.trim()==='设置').click()")
            await wait("document.querySelectorAll('.ui-theme-card').length===4")
        async def close_settings():
            await js("document.querySelector('.drawer-head button').click()")
            await wait("!document.querySelector('.drawer-head')")
        async def theme(label,id):
            await js(f"Array.from(document.querySelectorAll('.ui-theme-card')).find(b=>b.textContent.includes({json.dumps(label)})).click()")
            await wait(f"document.documentElement.dataset.uiTheme==={json.dumps(id)}")
        await call("Page.enable");await call("Runtime.enable");await call("Network.enable")
        await call("Network.setCacheDisabled",{"cacheDisabled":True})
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
        seed=await call("Page.addScriptToEvaluateOnNewDocument",{"source":"try { localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'none',fontScale:100,spriteAnimated:false,uiTheme:'jade'})); } catch {}"})
        await call("Page.navigate",{"url":BASE+"/?skipDisclaimer=1"})
        await wait("document.querySelector('.narrative-preview p')?.textContent.length>12")
        length=await js("document.querySelector('.narrative-preview p').textContent.length")
        await asyncio.sleep(.15)
        assert await js("document.querySelector('.narrative-preview p').textContent.length")>length
        assert await js("!document.querySelector('.chat-input-row textarea')")
        await shot('p18-phone-live-opening')
        await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        assert await js("document.querySelectorAll('[data-role=assistant]').length===1&&!document.querySelector('.narrative-preview')")
        await call("Page.removeScriptToEvaluateOnNewDocument",{"identifier":seed["identifier"]})
        palettes=[]
        labels=[('翠金星穹','jade'),('月海银蓝','lunar'),('紫晶秘仪','amethyst'),('曜石赤铜','ember')]
        for label,id in labels:
            await settings()
            await theme(label,id)
            await js("document.querySelector('.ui-theme-settings').scrollIntoView({block:'center'})")
            if id=='amethyst':await shot('p18-theme-picker')
            assert await js("document.querySelector('.ui-theme-card.on').getAttribute('aria-pressed')==='true'")
            assert await js("document.querySelector('.ui-theme-preview').getBoundingClientRect().width>100")
            await close_settings()
            palette=await js("({panel:getComputedStyle(document.documentElement).getPropertyValue('--panel').trim(),accent:getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),overflow:document.documentElement.scrollWidth>innerWidth+1})")
            assert not palette['overflow']
            palettes.append({'id':id,**palette})
            await shot('p18-phone-'+id)
            if id=='amethyst':
                await js("document.querySelector('.chat-menu-button').click()")
                await wait("Boolean(document.querySelector('.sprite-panel.ready'))")
                await wait("Math.abs(document.querySelector('.mobile-game-sidebar').getBoundingClientRect().left)<1")
                await shot('p18-drawer-amethyst')
                await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        assert len({p['panel'] for p in palettes})==4
        await call('Page.reload');await wait("document.documentElement.dataset.uiTheme==='ember'&&Boolean(document.querySelector('.chat-input-row textarea'))")
        await settings()
        await js("Array.from(document.querySelectorAll('.wallpaper-swatch')).find(b=>b.textContent.trim()==='星穹庭院').click()")
        assert await js("document.documentElement.dataset.uiTheme==='ember'&&document.querySelector('.app.has-wallpaper')!==null")
        await js("Array.from(document.querySelectorAll('.wallpaper-swatch')).find(b=>b.textContent.trim()==='纯深色').click()")
        await theme('月海银蓝','lunar');await close_settings()
        # Restore a long history to test follow-scroll behavior during real streaming.
        await js("fetch('/__qa/history',{method:'POST'}).then(r=>r.json())")
        await call('Page.reload');await wait("document.querySelectorAll('[data-role=user]').length===12")
        await set_input('.chat-input-row textarea','我向守夜人询问来信。')
        await js("document.querySelector('.chat-send').click()")
        await wait("document.querySelector('.narrative-preview p')?.textContent.length>12")
        assert await js("document.querySelectorAll('[data-role=user]').length===13")
        await shot('p18-phone-live-turn')
        await js("(()=>{let l=document.querySelector('.chat-transcript');l.scrollTop=0;l.dispatchEvent(new Event('scroll'))})()")
        await asyncio.sleep(.22)
        assert await js("document.querySelector('.chat-transcript').scrollTop<20")
        await wait("document.querySelector('.chat-send')?.textContent==='发送'&&!document.querySelector('.narrative-preview')")
        assert await js("document.querySelectorAll('[data-role=assistant]').length===14")
        assert await js("document.querySelector('.chat-transcript').scrollTop<20")
        await js("document.querySelector('.chat-to-latest').click()")
        # Force an interrupted network stream: draft restored, no committed assistant row.
        await set_input('.chat-input-row textarea','测试失败：我看看窗外。')
        await js("document.querySelector('.chat-send').click()")
        await wait("document.querySelector('.narrative-preview p')?.textContent.length>4")
        await wait("Boolean(document.querySelector('.chat-error'))&&!document.querySelector('.narrative-preview')")
        assert await js("document.querySelectorAll('[data-role=assistant]').length===14")
        assert await js("document.querySelector('.chat-input-row textarea').value.includes('测试失败')&&Boolean(document.querySelector('.chat-message--failed'))")
        # Sidebar skill still pays once while the narration streams.
        await js("document.querySelector('.chat-menu-button').click()")
        await wait("Boolean(document.querySelector('.sprite-panel.ready'))")
        await js("Array.from(document.querySelectorAll('.skill-row')).find(e=>e.textContent.includes('专注步法')).querySelector('.skill-pick').click()")
        await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        await set_input('.chat-input-row textarea','我稳住脚步，听听远处的钟声。')
        await js("document.querySelector('.chat-send').click()")
        await wait("Boolean(document.querySelector('.narrative-preview'))")
        await wait("document.querySelector('.chat-send')?.textContent==='发送'&&!document.querySelector('.narrative-preview')")
        state=await js("fetch('/api/state').then(r=>r.json())")
        assert state['state']['focus']==8,state['state']['focus']
        assert len([e for e in state['events'] if e['kind']=='skill.used'])==1
        assert not any(e['kind']=='narrative.delta' for e in state['events'])
        await call('Page.reload');await wait("document.querySelectorAll('[data-role=assistant]').length===15")
        assert await js("document.documentElement.dataset.uiTheme==='lunar'")
        # Keyboard-space and landscape layout keep the composer inside the viewport.
        for width,height,name in [(390,470,'p18-short-viewport'),(844,390,'p18-landscape')]:
            await call("Emulation.setDeviceMetricsOverride",{"width":width,"height":height,"deviceScaleFactor":1,"mobile":True})
            await wait("Boolean(document.querySelector('.mobile-chat'))")
            await wait(f"document.querySelector('.chat-composer').getBoundingClientRect().bottom<={height+1}")
            await shot(name)
        await call("Emulation.setDeviceMetricsOverride",{"width":1440,"height":1040,"deviceScaleFactor":1,"mobile":False})
        await wait("Boolean(document.querySelector('.app-shell'))")
        for label,id in labels:
            await settings(False);await theme(label,id);await close_settings()
            await shot('p18-desktop-'+id)
        await set_input('.composer-input','我抬头看看庭院。')
        await js("document.querySelector('.composer-bar button').click()")
        await wait("document.querySelector('.story-log .narrative-preview p')?.textContent.length>8")
        await shot('p18-desktop-live-turn')
        await wait("!document.querySelector('.story-log .narrative-preview')&&document.querySelector('.composer-bar button').textContent==='发送'")
        final=await js("fetch('/api/state').then(r=>r.json())")
        assert final['state']['focus']==8
        assert not errors,errors
        assert not bad,bad
        requests=json.load(urllib.request.urlopen(BASE+'/__qa/requests'))
        assert any(r['stream'] for r in requests) and any(r['clothing'] and not r['stream'] for r in requests)
        report={'palettes':palettes,'theme_controls_and_persistence':True,'wallpaper_independent':True,'opening_incremental_dom':True,'turn_incremental_dom':True,'desktop_incremental_dom':True,'reading_history_does_not_jump':True,'no_duplicate_final_messages':True,'interruption_retracts_preview_and_restores_draft':True,'skill_charged_once':True,'no_deltas_in_ledger':True,'phone_landscape_and_short_viewport':True,'real_http_stream_fixture':True,'real_network_model_used':False,'errors':errors,'bad_responses':bad}
        (ROOT/'docs/previews/p18-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':asyncio.run(main())
