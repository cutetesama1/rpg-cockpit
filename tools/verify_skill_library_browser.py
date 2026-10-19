"""End-to-end acceptance via real local model HTTP, UI file import and learning."""
import asyncio,base64,json,time,urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:18819'
async def main():
    for _ in range(60):
        try:
            if json.load(urllib.request.urlopen(BASE+'/api/health',timeout=1))['ok']:break
        except Exception:await asyncio.sleep(.1)
    page=json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19236/json/new?about:blank',method='PUT')))
    async with websockets.connect(page['webSocketDebuggerUrl'],max_size=30_000_000) as ws:
        seq=0;errors=[];bad=[]
        async def call(method,params=None):
            nonlocal seq
            seq+=1;ident=seq
            await ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
            while True:
                r=json.loads(await ws.recv())
                if r.get('method')=='Runtime.exceptionThrown':errors.append(r['params'])
                if r.get('method')=='Network.responseReceived':
                    x=r['params']['response']
                    if x['url'].startswith(BASE) and x['status']>=400:bad.append({'url':x['url'],'status':x['status']})
                if r.get('id')==ident:
                    assert 'error' not in r,r
                    return r.get('result',{})
        async def js(expr):
            r=await call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
            assert 'exceptionDetails' not in r,r
            return r.get('result',{}).get('value')
        async def wait(expr):
            for _ in range(180):
                if await js(expr):return
                await asyncio.sleep(.05)
            raise AssertionError(expr)
        async def click(label,selector='button'):
            await js(f"Array.from(document.querySelectorAll({json.dumps(selector)})).find(e=>e.textContent.trim()==={json.dumps(label)}).click()")
        async def set_value(selector,text,tag='textarea'):
            prototype='HTMLTextAreaElement' if tag=='textarea' else 'HTMLInputElement' if tag=='input' else 'HTMLSelectElement'
            event='change' if tag=='select' else 'input'
            await js(f"(()=>{{const e=document.querySelector({json.dumps(selector)});Object.getOwnPropertyDescriptor({prototype}.prototype,'value').set.call(e,{json.dumps(text)});e.dispatchEvent(new Event('{event}',{{bubbles:true}}));}})()")
        async def api(path,body=None):
            options='' if body is None else ',{method:"POST",headers:{"Content-Type":"application/json"},body:'+json.dumps(json.dumps(body,ensure_ascii=False))+'}'
            return await js(f"fetch({json.dumps(path)}{options}).then(async r=>{{if(!r.ok)throw new Error(await r.text());return r.json()}})")
        async def shot(name):
            await asyncio.sleep(.23)
            r=await call('Page.captureScreenshot',{'format':'png'})
            (ROOT/f'docs/previews/{name}.png').write_bytes(base64.b64decode(r['data']))
        async def settings(phone=True):
            if phone:
                await js("document.querySelector('.chat-menu-button').click()")
                await wait("Boolean(document.querySelector('.mobile-settings-button'))")
                await js("document.querySelector('.mobile-settings-button').click()")
            else:await js("Array.from(document.querySelectorAll('.sidebar button')).find(b=>b.textContent.trim()==='设置').click()")
            await wait("Boolean(document.querySelector('.skill-library-settings'))")
        async def send(text):
            await set_value('.chat-input-row textarea',text)
            await js("document.querySelector('.chat-send').click()")
            await wait("document.querySelector('.chat-send').textContent==='发送'&&!document.querySelector('.chat-generating')&&!document.querySelector('.narrative-preview')||Boolean(document.querySelector('.chat-error'))")
            await wait("!document.querySelector('.narrative-preview')&&!document.querySelector('.chat-generating')")
            assert await js("!document.querySelector('.chat-error')")
        await call('Page.enable');await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{'cacheDisabled':True})
        await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        seed=await call('Page.addScriptToEvaluateOnNewDocument',{'source':"try{localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'none',spriteAnimated:false,uiTheme:'amethyst'}));}catch{}"})
        await call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
        await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        await call('Page.removeScriptToEvaluateOnNewDocument',{'identifier':seed['identifier']})
        await settings()
        await click('导入300技能库')
        await wait("document.querySelector('.skill-library-settings').textContent.includes('共 300 个技能')")
        await js("document.querySelector('.skill-library-settings').scrollIntoView({block:'start'})")
        await shot('p19-imported-skill-library')
        await click('浏览技能库')
        await set_value('[aria-label="技能来源"]','standard-martial-magic','select')
        await wait("document.querySelectorAll('.skill-library-list details').length===30")
        await set_value('[aria-label="技能类型"]','magic','select')
        await set_value('[aria-label="技能等级"]','high','select')
        await wait("document.querySelector('.skill-library-modal').textContent.includes('共 50 个')")
        await shot('p19-magic-high-library')
        await set_value('[aria-label="搜索技能"]','日珥矢','input')
        await wait("document.querySelectorAll('.skill-library-list details').length===1")
        await js("document.querySelector('.skill-library-list summary').click()")
        assert await js("document.querySelector('.skill-library-list').textContent.includes('固定执行说明')")
        await shot('p19-fixed-skill-instructions')
        await click('关闭技能库')
        await click('为当前世界匹配技能池')
        await wait("document.querySelector('.skill-library-settings').textContent.includes('当前世界可学池：135 个')")
        # Custom authors import the exact same ZIP format through the real hidden file input.
        doc=await call('DOM.getDocument')
        node=await call('DOM.querySelector',{'nodeId':doc['root']['nodeId'],'selector':'.skill-library-settings input[type=file]'})
        await call('DOM.setFileInputFiles',{'nodeId':node['nodeId'],'files':[str(ROOT/'skill-libraries/author-template.zip')]})
        await wait("document.querySelector('.skill-library-settings').textContent.includes('共 301 个技能')")
        await js("document.querySelector('.drawer-head button').click()")
        await send('我想学火弹。')
        pool=await api('/api/world/skill-catalog');assert not any(e['known'] for e in pool['skills'])
        before=await api('/api/state');focus=before['state']['focus']
        await send('我向导师学习火弹。')
        learned=await api('/api/state');fire=next(s for s in learned['skills'] if s['name']=='火弹')
        assert fire['cost']=={'focus':1} and learned['state']['focus']==focus
        await js("document.querySelector('.chat-menu-button').click()")
        await wait("Array.from(document.querySelectorAll('.skill-row')).some(e=>e.textContent.includes('火弹'))")
        await shot('p19-learned-fire-skill')
        await js("Array.from(document.querySelectorAll('.skill-row')).find(e=>e.textContent.includes('火弹')).querySelector('.skill-pick').click()")
        await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        await js("document.querySelector('.chat-send').click()")
        await wait("!document.querySelector('.narrative-preview')&&!document.querySelector('.chat-generating')&&document.querySelector('.chat-send').textContent==='发送'")
        used=await api('/api/state');assert used['state']['focus']==focus-1
        assert len([e for e in used['events'] if e['kind']=='skill.used'])==1
        await api('/api/saves',{'slot':'library-qa','label':'技能学习后'})
        await api('/api/reset',{});await api('/api/saves/load',{'slot':'library-qa'})
        await call('Page.reload');await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        state=await api('/api/state');assert state['state']['focus']==focus-1 and any(s['name']=='火弹' for s in state['skills'])
        await api('/api/undo',{});await api('/api/undo',{})
        state=await api('/api/state');assert state['state']['focus']==focus and not any(s['name']=='火弹' for s in state['skills'])
        await call('Page.reload');await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        async def create_world(strong):
            await js("document.querySelector('.chat-menu-button').click()")
            await wait("Boolean(document.querySelector('.mobile-game-sidebar'))")
            await click('创建世界','.mobile-game-sidebar button')
            await wait("Boolean(document.querySelector('.builder-modal'))")
            await click('粘贴 AI 输出')
            title=('大法师背景' if strong else '学徒背景')+str(int(time.time()*1000))
            draft={'title':title,'prompts':{'pre':'你是一名十分强大的大法师，精通多系魔法。' if strong else '你是一名魔法学院刚入学的学徒。'}}
            await set_value('.builder-modal textarea',json.dumps(draft,ensure_ascii=False))
            await click('解析草稿')
            await wait(f"document.querySelector('.builder-preview input')?.value==={json.dumps(title)}")
            await click('创建并进入这个世界')
            await wait("!document.querySelector('.builder-modal')&&Boolean(document.querySelector('.chat-input-row textarea'))")
            state=await api('/api/state');pool=await api('/api/world/skill-catalog')
            assert state['pack']['title']==title
            assert sum(e['known'] for e in pool['skills'])==(135 if strong else 1)
            assert sum(e['known'] and e['tier']=='high' for e in pool['skills'])==(45 if strong else 0)
            return pool
        strong=await create_world(True)
        await settings();await js("document.querySelector('.skill-library-settings').scrollIntoView({block:'start'})")
        await shot('p19-powerful-mage-initial-skills')
        await js("document.querySelector('.drawer-head button').click()")
        novice=await create_world(False)
        await call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1040,'deviceScaleFactor':1,'mobile':False})
        await wait("Boolean(document.querySelector('.app-shell'))")
        await settings(False);await click('浏览技能库')
        await set_value('[aria-label="技能来源"]','world','select')
        await wait("document.querySelectorAll('.skill-library-list details').length===30")
        await shot('p19-desktop-world-skill-pool')
        assert await js("document.documentElement.scrollWidth<=innerWidth+1")
        requests=await api('/__qa/requests')
        assert any(r['phase']=='skill_selection' for r in requests)
        assert any(r['phase']=='skill_learning' and r['tool_names']==['learn_catalog_skills'] for r in requests)
        assert any(r['fixed_instruction_present'] for r in requests)
        assert not errors,errors
        assert not bad,bad
        report={'standard_zip_installed':300,'third_party_zip_installed':1,'magic_high_filter_count':50,'fixed_instruction_view':True,'current_world_pool':135,'desire_does_not_grant':True,'post_narrative_learning':True,'skill_cost_charged_once':True,'save_load_and_undo':True,'powerful_mage_initial_count':sum(e['known'] for e in strong['skills']),'novice_initial_count':sum(e['known'] for e in novice['skills']),'real_http_provider_fixture':True,'real_network_model_used':False,'errors':errors,'bad_responses':bad}
        (ROOT/'docs/previews/p19-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':asyncio.run(main())
