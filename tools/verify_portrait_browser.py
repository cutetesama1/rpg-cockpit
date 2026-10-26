"""Exercise the real UI/SSE and Canvas with the isolated portrait model fixture."""
import asyncio,base64,hashlib,json,subprocess,time,urllib.request
from pathlib import Path
import websockets
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:18871';CDP='http://127.0.0.1:19371'
OUT=ROOT/'docs/previews/portrait-v1';OUT.mkdir(parents=True,exist_ok=True)

async def verify():
    browser=subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--remote-debugging-port=19371','--user-data-dir='+str(ROOT/'build/portrait-edge'), 'about:blank'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        pages=[]
        for _ in range(100):
            try:
                pages=json.load(urllib.request.urlopen(CDP+'/json',timeout=2))
                if pages:break
            except Exception:pass
            await asyncio.sleep(.1)
        page=next(p for p in pages if p['type']=='page')
        async with websockets.connect(page['webSocketDebuggerUrl'],max_size=32_000_000) as ws:
            serial=0;errors=[];bad=[]
            async def call(method,params=None):
                nonlocal serial
                serial+=1;wanted=serial
                await ws.send(json.dumps({'id':wanted,'method':method,'params':params or {}}))
                while True:
                    message=json.loads(await ws.recv())
                    if message.get('method')=='Runtime.exceptionThrown':errors.append(message['params'])
                    if message.get('method')=='Network.responseReceived':
                        response=message['params']['response']
                        if '/api/pack/asset/' in response['url'] and response['status']>=400:bad.append(response['url'])
                    if message.get('id')==wanted:
                        if 'error' in message:raise RuntimeError(message['error'])
                        return message.get('result',{})
            async def js(source):
                result=await call('Runtime.evaluate',{'expression':source,'returnByValue':True,'awaitPromise':True})
                assert 'exceptionDetails' not in result,result
                return result.get('result',{}).get('value')
            async def wait(source):
                for _ in range(180):
                    if await js(source):return
                    await asyncio.sleep(.05)
                raise AssertionError('Timed out: '+source)
            async def click(label):
                await wait('Array.from(document.querySelectorAll("button")).some(b=>b.textContent.trim()==='+json.dumps(label)+'&&!b.disabled)')
                await js('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()==='+json.dumps(label)+').click()')
            async def shot(name):
                await asyncio.sleep(.15)
                data=await call('Page.captureScreenshot',{'format':'png'})
                (OUT/(name+'.png')).write_bytes(base64.b64decode(data['data']))
            async def pixel():
                data=await js('document.querySelector(".sprite-panel.ready .sprite-canvas").toDataURL()')
                return hashlib.sha256(base64.b64decode(data.split(',',1)[1])).hexdigest()
            await call('Page.enable');await call('Runtime.enable');await call('Network.enable')
            await call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
            await call('Page.addScriptToEvaluateOnNewDocument',{'source':"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({showSprite:true,spriteAnimated:false,spriteView:'full'}));"})
            await call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
            await wait('Boolean(document.querySelector(".sprite-panel.ready"))')
            hashes=[await pixel()];await shot('desktop-default')
            expected=[('stand','smile','witch'),('hold','smile','witch'),('guard','sad','witch'),('stand','sad','witch'),('cast','default','witch'),('hold','default','witch'),('hold','default','apple hairpin'),('hold','default','apple hairpin')]
            checks=[]
            for turn,(pose,expression,headwear) in enumerate(expected,1):
                await js('(()=>{const t=document.querySelector(".action-dock textarea"); t.focus();t.select()})()')
                await call('Input.insertText',{'text':'继续观察'})
                await click('发送')
                await wait(f'fetch("/api/state").then(r=>r.json()).then(s=>s.turn==={turn})')
                await wait('Boolean(document.querySelector(".sprite-panel.ready"))')
                await asyncio.sleep(.3)
                state=await js('fetch("/api/state").then(r=>r.json()).then(s=>s.state)')
                assert (state['pose'],state['expression'],state['headwear'])==(pose,expression,headwear),state
                current=await pixel();assert current!=hashes[-1]
                hashes.append(current);checks.append({'turn':turn,'pose':pose,'expression':expression,'pixel_sha256':current})
                await shot('desktop-turn-'+str(turn))
            # The actual debug form includes the new fields and usable labels.
            await click('调试台');await click('立绘/外观')
            await wait('Boolean(document.querySelector("[data-field-id=decoration_background] select"))')
            label=await js('document.querySelector("[data-field-id=pose] select").textContent')
            assert '施法表现' in label and '护身' in label
            await js('(()=>{const e=document.querySelector("[data-field-id=decoration_background] select");const v=Array.from(e.options).find(x=>x.textContent.includes("书房"))?.value;if(!v)throw new Error("No readable scene label");Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value").set.call(e,v);e.dispatchEvent(new Event("change",{bubbles:true}))})()')
            await click('应用改动')
            await wait('fetch("/api/state").then(r=>r.json()).then(s=>s.state.decoration_background!=="none")')
            await call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
            await wait('Boolean(document.querySelector(".sprite-panel.ready"))');await shot('desktop-decorations')
            decorated=await pixel()
            # The same authoritative state and pixel image appear in the phone drawer.
            await call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
            await wait('Boolean(document.querySelector(".chat-menu-button"))')
            await js('document.querySelector(".chat-menu-button").click()')
            await wait('Boolean(document.querySelector(".mobile-game-sidebar .sprite-panel.ready"))')
            assert await pixel()==decorated,'Phone and desktop portraits differ'
            await shot('phone-drawer')
            await call('Page.addScriptToEvaluateOnNewDocument',{'source':"const t=JSON.parse(localStorage.getItem('rpg-theme'));t.spriteAnimated=true;localStorage.setItem('rpg-theme',JSON.stringify(t));"})
            await call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
            await wait('Boolean(document.querySelector(".chat-menu-button"))');await js('document.querySelector(".chat-menu-button").click()')
            await wait('Boolean(document.querySelector(".mobile-game-sidebar .sprite-panel.ready"))')
            first=await pixel();await asyncio.sleep(.21);second=await pixel();assert first!=second,'Portrait motion did not animate'
            report={'kind':'real_form_and_sse_with_offline_model_fixture','turns':checks,'debug_controls':True,'readable_catalog_labels':True,'phone_matches_desktop':True,'procedural_animation_changes_pixels':True,'javascript_errors':errors,'failed_asset_urls':bad}
            assert not errors,errors;assert not bad,bad
            (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=True))
            await ws.send(json.dumps({"id":999999,"method":"Browser.close"}))
    finally:
        if browser.poll() is None:
            browser.terminate()
            try:browser.wait(timeout=10)
            except subprocess.TimeoutExpired:browser.kill()

if __name__=='__main__':asyncio.run(verify())
