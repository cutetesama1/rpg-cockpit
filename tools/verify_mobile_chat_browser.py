"""Drive phone chat, game drawer and real SSE using an offline fixture."""
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
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
        seed=await call("Page.addScriptToEvaluateOnNewDocument",{"source":"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'observatory',fontScale:100,spriteAnimated:false}))"})
        await call("Page.navigate",{"url":BASE+"/?skipDisclaimer=1"})
        await wait("document.querySelectorAll('.chat-message').length>20")
        await call("Page.removeScriptToEvaluateOnNewDocument",{"identifier":seed["identifier"]})
        assert await js("!document.querySelector('.app-shell')&&!document.querySelector('.gamebar')&&!document.querySelector('.mobile-game-sidebar')")
        assert await js("document.querySelector('.chat-transcript').scrollTop>1000")
        assert await js("document.querySelectorAll('[data-role=user]').length===18")
        assert await js("document.querySelector('.chat-dialogue-line').textContent.includes('请进')")
        await screenshot('p16-phone-chat')
        # Suggestions fill the input, without submitting it.
        before=await js("document.querySelectorAll('[data-role=user]').length")
        await click('询问星图')
        assert await js("document.querySelector('.chat-input-row textarea').value.includes('星图')")
        assert await js("document.querySelectorAll('[data-role=user]').length")==before
        await js("Array.from(document.querySelectorAll('.chat-input-modes label')).find(l=>l.textContent==='话语').click()")
        await js("Array.from(document.querySelectorAll('.chat-input-modes label')).find(l=>l.textContent==='心理').click()")
        await click('发送')
        await wait(f"document.querySelectorAll('[data-role=user]').length==={before+1}")
        # Browse older messages while the reply is pending: no forced jump on completion.
        await js("(()=>{let l=document.querySelector('.chat-transcript');l.scrollTop=0;l.dispatchEvent(new Event('scroll'))})()")
        await wait("!document.querySelector('.chat-generating')")
        await wait("document.querySelectorAll('[data-role=assistant]').length===21")
        assert await js("document.querySelector('.chat-transcript').scrollTop<20")
        assert await js("Array.from(document.querySelectorAll('[data-role=user]')).at(-1).textContent.includes('星图')")
        await screenshot('p16-history-scrolled-up')
        await click('回到最新 ↓')
        capture=json.load(urllib.request.urlopen(BASE+'/__qa/requests'))
        action=next(row['action'] for row in capture if row['phase']=='narrator')
        assert set(action['modes'])=={'action','speech','thought'},action
        assert action['text']=='我询问守夜人关于星图的事情。',action
        # Drawer order and bottom settings; choosing a skill must keep the drawer open.
        await js("document.querySelector('.chat-menu-button').click()")
        await wait("Boolean(document.querySelector('.mobile-game-sidebar .sprite-panel.ready'))")
        order=await js("Array.from(document.querySelectorAll('.mobile-game-sidebar h2')).slice(0,3).map(e=>e.textContent)")
        assert order[:2]==['立绘','状态'],order
        buttons=await js("Array.from(document.querySelectorAll('.mobile-game-sidebar button')).map(e=>e.textContent.trim())")
        assert buttons[-1]=='设置',buttons[-4:]
        await screenshot('p16-phone-drawer')
        await js("Array.from(document.querySelectorAll('.skill-row')).find(e=>e.textContent.includes('专注步法')).querySelector('.skill-pick').click()")
        assert await js("Boolean(document.querySelector('.mobile-game-sidebar'))")
        assert await js("document.querySelector('.mobile-game-sidebar').textContent.includes('预扣')")
        await js("document.querySelector('.mobile-settings-button').scrollIntoView({block:'end'})")
        await screenshot('p16-sidebar-settings-bottom')
        await js("document.querySelector('.mobile-settings-button').click()")
        await wait("document.querySelectorAll('.wallpaper-swatch').length>6")
        await click('纯深色');await wait("!document.querySelector('.app').classList.contains('has-wallpaper')")
        await click('星穹庭院');await wait("document.querySelector('.app').classList.contains('has-wallpaper')")
        await click('关闭')
        # Enter adds a newline on phone; the explicit send button submits a chosen skill.
        await js("document.querySelector('.chat-input-row textarea').focus()")
        await call('Input.insertText',{'text':'我使用选中的步法。'})
        await click('发送');await wait("Boolean(document.querySelector('.chat-generating'))");await wait("!document.querySelector('.chat-generating')")
        status=json.load(urllib.request.urlopen(BASE+'/api/state'))
        assert status['state']['focus']==8,status['state']['focus']
        count=await js("document.querySelectorAll('.chat-message').length")
        await call('Page.reload');await wait(f"document.querySelectorAll('.chat-message').length==={count}")
        assert await js("document.querySelector('.chat-transcript').textContent.includes('我使用选中的步法。')")
        # A failed turn retains the player message, marks it failed, and restores the draft.
        await js("document.querySelector('.chat-input-row textarea').focus()")
        await call('Input.insertText',{'text':'测试失败'})
        await click('发送');await wait("Boolean(document.querySelector('.chat-generating'))");await wait("!document.querySelector('.chat-generating')")
        assert await js("document.querySelector('.chat-input-row textarea').value==='测试失败'")
        assert await js("document.querySelector('.chat-message--failed').textContent.includes('测试失败')")
        assert await js("document.querySelector('.chat-message--notice').textContent.includes('状态已回滚')")
        # Undo the skill turn: both messages disappear and focus is restored.
        before_undo=await js("document.querySelectorAll('.chat-message').length")
        await js("document.querySelector('.chat-menu-button').click()")
        await wait("Boolean(document.querySelector('.mobile-game-sidebar'))")
        await click('撤销上一回合')
        await wait(f"document.querySelectorAll('.chat-message').length==={before_undo-2}")
        status=json.load(urllib.request.urlopen(BASE+'/api/state'))
        assert status['state']['focus']==10,status['state']['focus']
        # Keyboard-height simulation: composer remains inside the viewport.
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":470,"deviceScaleFactor":1,"mobile":True})
        await wait("document.querySelector('.chat-composer').getBoundingClientRect().bottom<=471")
        await screenshot('p16-keyboard-height')
        await call("Emulation.setDeviceMetricsOverride",{"width":844,"height":390,"deviceScaleFactor":1,"mobile":True})
        await wait("document.querySelector('.chat-composer').getBoundingClientRect().bottom<=391")
        assert await js("!document.querySelector('.app-shell')")
        await screenshot('p16-landscape-chat')
        for scale in (50,160):
            await js(f"localStorage.setItem('rpg-theme',JSON.stringify({{wallpaper:'observatory',fontScale:{scale},fontTarget:'all',spriteAnimated:false}}))")
            await call('Page.reload');await wait("Boolean(document.querySelector('.mobile-chat'))")
            size=await js("parseFloat(getComputedStyle(document.querySelector('.chat-input-row textarea')).fontSize)")
            assert abs(size-16*scale/100)<.01,(scale,size)
            assert await js("document.documentElement.scrollWidth<=innerWidth+1")
        await js("localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'observatory',fontScale:100,fontTarget:'narrative',spriteAnimated:false}))")
        await call('Page.reload');await wait("Boolean(document.querySelector('.mobile-chat'))")
        # Desktop still uses its own dashboard; returning to phone restores the chat view.
        await call("Emulation.setDeviceMetricsOverride",{"width":1440,"height":1040,"deviceScaleFactor":1,"mobile":False})
        await wait("Boolean(document.querySelector('.app-shell'))")
        await screenshot('p16-desktop-unchanged')
        await call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
        await wait("Boolean(document.querySelector('.mobile-chat'))")
        assert not errors,errors
        assert not bad,bad
        report={'phone_chat_separate_from_dashboard':True,'player_and_ai_history':True,'history_survives_reload':True,'dialogue_line_breaks':True,'no_forced_scroll_when_reading_history':True,'suggestion_fills_without_sending':True,'checkbox_modes_received':action['modes'],'drawer_order':order,'settings_last':True,'skill_selection_and_payment':True,'wallpaper_picker':True,'short_viewport_composer_visible':True,'landscape_chat':True,'desktop_dashboard_retained':True,'font_scale_50_and_160':True,'failed_input_preserved':True,'undo_removes_pair_and_restores_resource':True,'errors':errors,'bad_responses':bad}
        (ROOT/'docs/previews/p16-mobile-chat-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
