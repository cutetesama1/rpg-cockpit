from pathlib import Path
exec(((Path(__file__).resolve().parents[1]/'tools/verify_multiplayer_browser.py')).read_text(encoding='utf-8').split('async def verify():')[0])
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/previews/tunnel-manual-start';OUT.mkdir(exist_ok=True)
CDP='http://127.0.0.1:19498'
def api(path,body=None):
    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'}),timeout=30))
async def verify():
    browser=subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=19498','--user-data-dir='+str(ROOT/'build/manual-single-edge'),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(100):
            try:pages=json.load(urllib.request.urlopen(CDP+'/json/list',timeout=1));break
            except Exception:await asyncio.sleep(.1)
        async with websockets.connect(next(p['webSocketDebuggerUrl'] for p in pages if p['type']=='page'),max_size=32_000_000) as ws:
            page=Page(ws);await page.call('Page.enable');await page.call('Runtime.enable');await page.call('Network.enable')
            await page.call('Page.addScriptToEvaluateOnNewDocument',{'source':"localStorage.setItem('rpg-welcome-seen','1');localStorage.setItem('rpg-age-ack','1');localStorage.setItem('rpg-theme',JSON.stringify({wallpaper:'night',showSprite:false,textSpeed:0}));"})
            checks=[]
            for width,mobile in [(1440,False),(390,True)]:
                api('/api/world/builder/apply',{'id':'manual-world-'+str(width)+'-'+str(time.time_ns()),'draft':{'title':'等待生成的旅途','prompts':{'pre':'一段适合全年龄的森林冒险。'}}})
                count=len(api('/__qa/party')['requests'])
                await page.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':900 if not mobile else 844,'deviceScaleFactor':1,'mobile':mobile})
                await page.call('Page.navigate',{'url':BASE+'/?skipDisclaimer=1'})
                await page.wait('Array.from(document.querySelectorAll(".generate-world")).some(b=>b.getClientRects().length>0)')
                await asyncio.sleep(.7);assert len(api('/__qa/party')['requests'])==count
                assert not api('/api/state')['opening_generated']
                await page.call('Page.reload');await page.wait('Array.from(document.querySelectorAll(".generate-world")).some(b=>b.getClientRects().length>0)')
                assert len(api('/__qa/party')['requests'])==count
                await page.shot('phone-before-generate' if mobile else 'desktop-before-generate')
                await page.click('生成世界')
                await page.wait('fetch("/api/state").then(r=>r.json()).then(s=>s.opening_generated)')
                await page.wait('!document.querySelector(".generate-world")')
                assert len(api('/__qa/party')['requests'])==count+2
                await page.shot('phone-after-generate' if mobile else 'desktop-after-generate')
                await page.call('Page.reload');await asyncio.sleep(.7);assert len(api('/__qa/party')['requests'])==count+2
                checks.append({'width':width,'no_model_on_creation_or_reload':True,'explicit_click_generates_once':True,'reload_preserves_generated_world':True})
            assert not page.errors,page.errors
            report={'single_player':checks,'javascript_errors':len(page.errors),'physical_android_device_tested':False,'external_models_used':False}
            (OUT/'single-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
    finally:subprocess.run(['taskkill','/PID',str(browser.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
asyncio.run(verify())
