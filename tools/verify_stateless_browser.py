"""End-to-end acceptance via real local model HTTP, UI file import and learning."""
import asyncio,base64,json,time,urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:18831'
async def main():
    for _ in range(60):
        try:
            if json.load(urllib.request.urlopen(BASE+'/api/health',timeout=1))['ok']:break
        except Exception:await asyncio.sleep(.1)
    page=json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19238/json/new?about:blank',method='PUT')))
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
            await wait(f"Array.from(document.querySelectorAll({json.dumps(selector)})).some(e=>e.textContent.trim()==={json.dumps(label)}&&!e.disabled)")
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
        await call('Page.addScriptToEvaluateOnNewDocument',{'source':"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'none',spriteAnimated:false,uiTheme:'jade'}));"})
        await call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
        await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        async def menu():
            await js("document.querySelector('.chat-menu-button').click()")
            await wait("Boolean(document.querySelector('.mobile-game-sidebar'))")
        async def portrait():
            await wait("Boolean(document.querySelector('.sprite-panel.ready'))")
            pixels=await js("(()=>{const c=document.querySelector('.sprite-canvas'),a=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let n=0;for(let i=3;i<a.length;i+=4)if(a[i])n++;return n})()")
            assert pixels>100,pixels
            return pixels
        await menu();pixels=await portrait();await shot('p21-phone-portrait')
        await click('世界构筑','.mobile-game-sidebar button');await wait("Boolean(document.querySelector('.world-modal'))")
        await click('基础数值','.world-modal button')
        await set_value('[aria-label="hp名称"]','气血','input')
        await set_value('[aria-label="hp初始值"]','200','input')
        await set_value('[aria-label="hp上限"]','200','input')
        await set_value('[aria-label="hp当前值"]','57','input')
        await click('保存基础数值','.world-modal button')
        await wait("fetch('/api/state').then(r=>r.json()).then(s=>s.state.hp===57&&s.fields.find(f=>f.id==='hp').max===200)")
        state=await api('/api/state');assert state['state']['hp']==57 and next(f for f in state['fields'] if f['id']=='hp')['max']==200
        await shot('p21-numeric-editor')
        await js("document.querySelector('.world-modal .modal-head button').click()")
        await settings();await click('导入300技能库');await wait("document.querySelector('.skill-library-settings').textContent.includes('共 300 个技能')")
        await click('为当前世界匹配技能池');await wait("document.querySelector('.skill-library-settings').textContent.includes('当前世界可学池：135 个')")
        await js("document.querySelector('.drawer-head button').click()")
        await send('我参加训练，受伤后换装。')
        state=await api('/api/state');assert state['state']['hp']==54 and state['state']['upper']=='hoodie'
        assert state['story_facts']['story.met_mira']['value'] is True
        await menu();await portrait();await shot('p21-updated-state-and-portrait')
        await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        await send('我向导师学习火弹。')
        state=await api('/api/state');fire=next(s for s in state['skills'] if s['name']=='火弹');focus=state['state']['focus']
        await menu();await js("Array.from(document.querySelectorAll('.skill-row')).find(e=>e.textContent.includes('火弹')).querySelector('.skill-pick').click()")
        await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        await js("document.querySelector('.chat-send').click()")
        await wait("!document.querySelector('.narrative-preview')&&!document.querySelector('.chat-generating')&&document.querySelector('.chat-send').textContent==='发送'")
        state=await api('/api/state');assert state['state']['focus']==focus-1
        await api('/api/saves',{'slot':'stateless-browser'});before=state['events']
        await api('/api/settings',{});assert (await api('/api/state'))['events']==before
        await api('/api/undo',{});await api('/api/undo',{})
        state=await api('/api/state');assert state['state']['focus']==focus and not any(s['name']=='火弹' for s in state['skills'])
        await api('/api/saves/load',{'slot':'stateless-browser'})
        assert (await api('/api/state'))['state']['focus']==focus-1
        await call('Page.reload');await wait("Boolean(document.querySelector('.chat-input-row textarea'))")
        await menu();await click('创建世界','.mobile-game-sidebar button')
        await wait("Boolean(document.querySelector('.builder-modal'))");await click('粘贴 AI 输出')
        fields=[{'id':'life','label':'生命','type':'int','default':1200,'min':0,'max':1200,'display':'bar'},{'id':'crystal','label':'琉璃魔力','type':'int','default':600,'min':0,'max':600,'display':'bar'},{'id':'coins','label':'学院金币','type':'int','default':80,'min':0,'max':None,'display':'number'}]
        draft={'title':'强大法师与自定义资源','prompts':{'pre':'你是一名十分强大的大法师，已经精通多种魔法。'},'state':{'fields':fields,'resource_bindings':{'health':'life','mana':'crystal','effort':'','currency':'coins'}}}
        await set_value('.builder-modal textarea',json.dumps(draft,ensure_ascii=False));await click('解析草稿')
        await wait("Boolean(document.querySelector('.builder-preview .state-editor'))")
        await set_value('[aria-label="crystal初始值"]','900','input');await set_value('[aria-label="crystal上限"]','900','input')
        await shot('p21-world-initial-resources')
        await click('创建并进入这个世界');await wait("!document.querySelector('.builder-modal')&&Boolean(document.querySelector('.chat-input-row textarea'))")
        state=await api('/api/state');pool=await api('/api/world/skill-catalog')
        assert state['state']['crystal']==900 and 'focus' not in state['state']
        assert sum(e['known'] for e in pool['skills'])==135
        assert all(set(s['cost'])<={'crystal'} for s in state['skills'])
        await menu();await portrait();await shot('p21-powerful-mage-known-skills')
        await js("document.querySelector('.mobile-game-sidebar-head button').click()")
        requests=await api('/__qa/requests')
        backend=[r for r in requests if r['phase']=='settlement']
        assert backend and all(r['history_absent'] and r['roles']==['system','user'] and r['tool_names']==['settle_turn'] for r in backend)
        assert all(not r['tool_names'] for r in requests if r['phase']=='narration')
        assert max(r['candidate_count'] for r in backend)<=1
        assert not errors,errors
        report={'phone_portrait_alpha_pixels':pixels,'numeric_editor_preserves_current_and_changes_cap':True,'hp_57_to_54':True,'wardrobe_update_in_same_batch':True,'unknown_flag_recorded_as_story_fact':True,'canonical_skill_learning_and_single_cost':True,'model_settings_preserve_events':True,'save_load_and_undo':True,'powerful_mage_known_presets':135,'custom_mana_initial_and_cap':900,'no_legacy_focus_in_custom_world':True,'all_backend_calls_stateless':True,'all_narrator_calls_without_tools':True,'max_backend_skill_candidates':max(r['candidate_count'] for r in backend),'javascript_errors':errors,'bad_responses':bad,'real_network_model_used':False,'real_android_device_tested':False}
        (ROOT/'docs/previews/p21-browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=True))
asyncio.run(main())
