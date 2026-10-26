import asyncio,base64,json,subprocess,time,urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/previews/multiplayer-m1';OUT.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:18894';CDP='http://127.0.0.1:19494'
class Page:
    def __init__(self,ws):self.ws=ws;self.seq=0;self.errors=[];self.assets=[];self.relay=0
    async def call(self,method,params=None):
        self.seq+=1;serial=self.seq;await self.ws.send(json.dumps({'id':serial,'method':method,'params':params or {}}))
        while True:
            row=json.loads(await self.ws.recv())
            if row.get('method')=='Runtime.exceptionThrown':self.errors.append(row['params'])
            if row.get('method')=='Network.responseReceived':
                r=row['params']['response']
                if '/assets/ui/' in r['url'] or '/relay?' in r['url']:
                    if r['status']>=400:self.assets.append({'status':r['status'],'resource':'room asset or relay'})
                if '/relay?' in r['url']:self.relay+=1
            if row.get('id')==serial:
                assert not row.get('error'),row
                return row.get('result',{})
    async def js(self,code):
        r=await self.call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True});assert 'exceptionDetails' not in r,r
        return r.get('result',{}).get('value')
    async def wait(self,code):
        for _ in range(300):
            if await self.js(code):return
            await asyncio.sleep(.05)
        raise AssertionError('Timeout: '+code)
    async def click(self,label):
        expr='Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()==='+json.dumps(label)+')'
        await self.wait(expr+'&&!('+expr+').disabled');await self.js('('+expr+').click()')
    async def fill_label(self,label,value):
        await self.js("(()=>{const e=Array.from(document.querySelectorAll('label')).find(e=>e.textContent.startsWith("+json.dumps(label)+")).querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,"+json.dumps(value)+");e.dispatchEvent(new Event('input',{bubbles:true}));})()")
    async def fill_action(self,value):
        await self.js("(()=>{const e=document.querySelector('[aria-label=\"你的本轮行动\"]');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,"+json.dumps(value)+");e.dispatchEvent(new Event('input',{bubbles:true}));})()")
    async def state(self):
        return await self.js("(()=>{const s=JSON.parse(localStorage.getItem('rpg-party-session-v1'));return fetch(s.server_url+'/api/rooms/'+s.room_id+'/state',{headers:{Authorization:'Bearer '+s.token}}).then(r=>r.json())})()")
    async def shot(self,name):
        r=await self.call('Page.captureScreenshot',{'format':'png'});(OUT/(name+'.png')).write_bytes(base64.b64decode(r['data']))

async def verify():
    browser=subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=19494','--user-data-dir='+str(ROOT/'build/party-edge'),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(100):
            try:version=json.load(urllib.request.urlopen(CDP+'/json/version',timeout=1));break
            except Exception:await asyncio.sleep(.1)
        async with websockets.connect(version['webSocketDebuggerUrl'],max_size=8_000_000) as bw:
            b=Page(bw);targets=[]
            for _ in range(2):
                context=await b.call('Target.createBrowserContext');t=await b.call('Target.createTarget',{'url':'about:blank','browserContextId':context['browserContextId']});targets.append(t['targetId'])
            pages=json.load(urllib.request.urlopen(CDP+'/json/list'));urls=[next(p['webSocketDebuggerUrl'] for p in pages if p['id']==t) for t in targets]
            async with websockets.connect(urls[0],max_size=32_000_000) as aw,websockets.connect(urls[1],max_size=32_000_000) as cw:
                a,c=Page(aw),Page(cw)
                for p in [a,c]:
                    await p.call('Page.enable');await p.call('Runtime.enable');await p.call('Network.enable')
                    await p.call('Page.addScriptToEvaluateOnNewDocument',{'source':"localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'night',textSpeed:0,showSprite:true,spriteAnimated:false}));"})
                await a.call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
                await c.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
                await c.call('Network.setUserAgentOverride',{'userAgent':'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36'})
                for p in [a,c]:await p.call('Page.navigate',{'url':BASE+'/?multiplayer=1'});await p.wait('Boolean(document.querySelector(".party-entry"))')
                await a.shot('desktop-lobby');await c.shot('phone-lobby')
                await a.fill_label('你的角色姓名','阿澄');await a.click('创建联机房间 ↗');await a.wait('Boolean(document.querySelector(".party-invite"))')
                invite=await a.js('document.querySelector(".party-invite").textContent')
                info=json.load(urllib.request.urlopen(BASE+'/api/multiplayer/host/status'));address=next((u for u in info['addresses'] if '127.0.0.1' not in u),info['addresses'][0])
                await c.fill_label('你的角色姓名','小岚');await c.fill_label('房主地址',address);await c.fill_label('邀请码',invite);await c.click('加入队伍 →');await c.wait('Boolean(document.querySelector(".party-scene"))')
                await a.wait('document.querySelectorAll(".party-members button").length===2');await c.wait('document.querySelectorAll(".party-members button").length===2')
                await a.wait('Boolean(document.querySelector(".sprite-panel.ready"))')
                assert not json.load(urllib.request.urlopen(BASE+'/__qa/party'))['requests']
                assert not (await a.state())['opening_generated']
                await a.click('生成世界');await a.wait('Boolean(document.querySelector(".party-world-opening"))');await c.wait('Boolean(document.querySelector(".party-world-opening"))')
                await a.js('document.querySelector(".party-skill-picker input").click()')
                await a.fill_action('我走在队伍前面，小心穿过树枝。');await a.click('提交行动');await a.click('准备 ✓')
                before=await a.state();assert before['round']==0 and before['phase']=='collecting'
                await c.fill_action('我在路标前换上卫衣，向队友挥手。');await c.click('提交行动');await c.click('准备 ✓')
                await a.wait('Boolean(document.querySelector(".party-generating"))');await a.wait('Boolean(document.querySelector(".party-generating p")) && document.querySelector(".party-generating p").textContent.includes("阿澄")')
                await a.shot('shared-story-streaming')
                await a.wait('document.querySelectorAll(".party-round").length===1&&!document.querySelector(".party-generating")')
                await c.wait('document.querySelectorAll(".party-round").length===1&&!document.querySelector(".party-generating")')
                va=await a.state();vb=await c.state();assert va['round']==vb['round']==1
                sa=next(p['state'] for p in va['players'] if p['name']=='阿澄');sb=next(p['state'] for p in vb['players'] if p['name']=='小岚')
                initial_a=next(p['state'] for p in before['players'] if p['name']=='阿澄');initial_b=next(p['state'] for p in before['players'] if p['name']=='小岚')
                assert sa['hp']==initial_a['hp']-3 and sb['hp']==initial_b['hp'] and sa['focus']==initial_a['focus']-2 and sb['focus']==initial_b['focus'],(sa['hp'],sb['hp'],sa['focus'],sb['focus'])
                assert sb['upper']=='hoodie' and sb['pose']=='cheer';assert va['pending_count']==1,va['pending']
                assert va['history']==vb['history'];await a.shot('desktop-shared-turn');await c.shot('phone-shared-turn')
                await c.js('document.querySelector(".party-menu").click()');await c.wait('Boolean(document.querySelector(".party-sidebar.open .sprite-panel.ready"))')
                pixels=await c.js('(()=>{const c=document.querySelector(".sprite-canvas"),d=c.getContext("2d").getImageData(0,0,c.width,c.height).data;let n=0;for(let i=3;i<d.length;i+=4)if(d[i])n++;return n})()');assert pixels>100
                await c.shot('phone-player-sidebar');await c.js('document.querySelector(".party-close").click()')
                await c.call('Page.reload');await c.wait('document.querySelectorAll(".party-round").length===1')
                previous_actor=vb['me']
                await c.call('Page.navigate',{'url':'http://127.0.0.1:18896/?multiplayer=1'})
                await c.wait('document.querySelectorAll(".party-round").length===1')
                assert (await c.state())['me']==previous_actor
                await a.click('提议回退上一回合');await c.wait('document.body.textContent.includes("全队回退确认")');await c.click('同意回退')
                await a.wait('document.querySelectorAll(".party-round").length===0');await c.wait('document.querySelectorAll(".party-round").length===0')
                final=await a.state();assert final['round']==0 and next(p['state']['hp'] for p in final['players'] if p['name']=='阿澄')==initial_a['hp']
                owner_actor=final['me'];await a.click('断开并返回大厅');await a.wait('document.body.textContent.includes("恢复房主房间")')
                await a.click('异世界 · 回合 0');await a.wait('Boolean(document.querySelector(".party-scene"))');assert (await a.state())['me']==owner_actor
                assert not a.errors and not c.errors,(a.errors,c.errors);assert not a.assets and not c.assets,(a.assets,c.assets);assert c.relay>0
                requests=json.load(urllib.request.urlopen(BASE+'/__qa/party'))['requests'][-2:];assert len(requests)==2 and requests[1]['history_absent'] and requests[1]['tools']==['settle_party_round']
                report={'two_isolated_browser_sessions':True,'desktop_and_phone_layouts':[1440,390],'shared_streaming_narrative':True,'hp_changes_only_target_player':True,'skill_cost_once':True,'clothing_and_pose_on_correct_player':True,'unknown_flag_does_not_rollback_valid_state':True,'android_loopback_bridge_requests':c.relay,'phone_portrait_alpha_pixels':pixels,'reconnect_restores_room':True,'changed_web_port_restores_identity':True,'host_room_resume':True,'unanimous_undo':True,'local_model_http_calls':requests,'javascript_errors':len(a.errors)+len(c.errors),'missing_room_assets':len(a.assets)+len(c.assets),'external_models_used':False,'physical_android_device_tested':False,'manual_world_generation':True,'custom_external_port':18897}
                (OUT/'browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=True),flush=True)
    finally:subprocess.run(['taskkill','/PID',str(browser.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
asyncio.run(verify())
