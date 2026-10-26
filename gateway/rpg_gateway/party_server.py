"""Isolated LAN listener. Never mounts the host's settings or single-player API."""
from __future__ import annotations
import asyncio,json,socket,threading,time
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,Header,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse,RedirectResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field
from rpg_core.party import PartyError,PartyManager
from rpg_core.party_contracts import PartyIntent
from .http_identity import USER_AGENT

class Body(BaseModel):model_config=ConfigDict(extra='forbid')
class Join(Body):
    invite_code:str=Field(min_length=8,max_length=80)
    name:str=Field(min_length=1,max_length=40)
    request_id:str=Field(min_length=16,max_length=120)
class Intent(Body):
    request_id:str=Field(min_length=8,max_length=120)
    round_token:str
    expected_intent_revision:int=Field(ge=0)
    intent:PartyIntent
class Ready(Body):
    request_id:str=Field(min_length=8,max_length=120)
    round_token:str
    intent_revision:int=Field(ge=0)
    ready:bool
class Retry(Body):request_id:str=Field(min_length=8,max_length=120)
class Vote(Body):
    proposal_id:str
    agree:bool
class Events(Body):after:int=Field(default=0,ge=0)
class HostRoom(Body):
    request_id:str=Field(min_length=16,max_length=120)
    name:str=Field(min_length=1,max_length=40)
    capacity:Literal[2,3,4]=4
    unique_items:list[str]=Field(default_factory=list,max_length=100)
class ClientSession(Body):
    server_url:str=Field(max_length=200)
    room_id:str=Field(pattern=r'^room_[a-f0-9]{24}$')
    player_id:str=Field(pattern=r'^actor_[a-f0-9]{24}$')
    token:str=Field(pattern=r'^[a-f0-9]{64}$')
class ClientSave(Body):session:ClientSession|None=None
class ConnectionSelection(Body):
    server_url:str=Field(min_length=8,max_length=300)

def bearer(value):
    if not value or not value.startswith('Bearer '):raise PartyError('请先加入房间',401)
    return value[7:]

def create_party_app(parties:PartyManager,ui_dist:Path):
    app=FastAPI(title='RPG Cockpit · Cooperative LAN',docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['GET','POST','PUT'],allow_headers=['Authorization','Content-Type','ngrok-skip-browser-warning'],allow_credentials=False)
    @app.exception_handler(PartyError)
    async def party_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=exc.status)
    @app.get('/api/party/health')
    def health():return {'ok':True,'mode':'cooperative','protocol':1,'max_players':4}
    @app.post('/api/rooms/join')
    def join(body:Join):return parties.join(body.invite_code,body.name,body.request_id)
    @app.get('/api/rooms/{room_id}/state')
    def state(room_id:str,authorization:str|None=Header(default=None)):return parties.view(room_id,bearer(authorization))
    @app.put('/api/rooms/{room_id}/intent')
    def intent(room_id:str,body:Intent,authorization:str|None=Header(default=None)):
        return parties.intent(room_id,bearer(authorization),body.request_id,body.round_token,body.expected_intent_revision,body.intent.model_dump(mode='json'))
    @app.post('/api/rooms/{room_id}/ready')
    def ready(room_id:str,body:Ready,authorization:str|None=Header(default=None)):
        return parties.ready(room_id,bearer(authorization),body.request_id,body.round_token,body.intent_revision,body.ready)
    @app.post('/api/rooms/{room_id}/generate')
    def generate(room_id:str,body:Retry,authorization:str|None=Header(default=None)):return parties.generate_opening(room_id,bearer(authorization),body.request_id)
    @app.post('/api/rooms/{room_id}/retry')
    def retry(room_id:str,body:Retry,authorization:str|None=Header(default=None)):return parties.retry(room_id,bearer(authorization),body.request_id)
    @app.post('/api/rooms/{room_id}/leave')
    def leave(room_id:str,authorization:str|None=Header(default=None)):return parties.leave(room_id,bearer(authorization))
    @app.post('/api/rooms/{room_id}/cancel')
    def cancel(room_id:str,authorization:str|None=Header(default=None)):return parties.cancel_failed(room_id,bearer(authorization))
    @app.post('/api/rooms/{room_id}/undo')
    def undo(room_id:str,authorization:str|None=Header(default=None)):return parties.propose_undo(room_id,bearer(authorization))
    @app.post('/api/rooms/{room_id}/undo/vote')
    def vote(room_id:str,body:Vote,authorization:str|None=Header(default=None)):return parties.vote_undo(room_id,bearer(authorization),body.proposal_id,body.agree)
    @app.post('/api/rooms/{room_id}/pending/{pending_id}/dismiss')
    def dismiss(room_id:str,pending_id:str,authorization:str|None=Header(default=None)):return parties.dismiss(room_id,bearer(authorization),pending_id)
    @app.get('/api/rooms/{room_id}/sheet')
    def sheet(room_id:str,authorization:str|None=Header(default=None)):return parties.sheet(room_id,bearer(authorization))
    @app.get('/api/rooms/{room_id}/assets/{relative:path}')
    def asset(room_id:str,relative:str,authorization:str|None=Header(default=None)):
        return FileResponse(parties.asset(room_id,bearer(authorization),relative),headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})
    @app.post('/api/rooms/{room_id}/events')
    async def events(room_id:str,body:Events,request:Request,authorization:str|None=Header(default=None)):
        token=bearer(authorization);parties.view(room_id,token)
        async def stream():
            cursor=body.after;heartbeat=time.monotonic()
            while not parties.closed and not await request.is_disconnected():
                try:rows=await asyncio.to_thread(parties.events,room_id,token,cursor)
                except PartyError:
                    yield 'event: session.closed\ndata: {}\n\n';break
                for row in rows:
                    cursor=row['seq'];yield f'id: {cursor}\nevent: {row["kind"]}\ndata: '+json.dumps(row,ensure_ascii=False)+'\n\n'
                if time.monotonic()-heartbeat>15:yield ': heartbeat\n\n';heartbeat=time.monotonic()
                if not rows:await asyncio.sleep(.3)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    # Unknown API paths must return 404 instead of the single-player page.
    @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH'])
    def unavailable(path:str):return JSONResponse({'detail':'联机端口不提供此接口'},status_code=404)
    @app.get('/')
    def home(request:Request):
        if request.query_params.get('multiplayer')!='1':return RedirectResponse('/?multiplayer=1')
        if (ui_dist/'index.html').is_file():return FileResponse(ui_dist/'index.html')
        return JSONResponse({'mode':'cooperative','ui':'not built'})
    if ui_dist.is_dir():app.mount('/',StaticFiles(directory=ui_dist,html=True),name='party-ui')
    return app

class PartyHost:
    def __init__(self,parties,ui_dist,port=8790):
        self.parties=parties;self.ui_dist=ui_dist;self.port=port;self.thread=None;self.server=None;self.lock=threading.Lock()
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            import uvicorn
            sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:sock.bind(('0.0.0.0',self.port));sock.listen(128)
            except OSError:
                sock.close();raise PartyError('联机端口已被占用，请关闭其他房主服务后重试',409) from None
            self.port=sock.getsockname()[1]
            self.server=uvicorn.Server(uvicorn.Config(create_party_app(self.parties,self.ui_dist),host='0.0.0.0',port=self.port,log_level='warning',access_log=False,lifespan='off'))
            self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[sock]},daemon=True,name='rpg-party-lan');self.thread.start()
            for _ in range(100):
                if self.server.started:return
                if not self.thread.is_alive():break
                time.sleep(.02)
            raise PartyError('联机服务启动失败',500)
    def addresses(self):
        addresses={'127.0.0.1'}
        try:addresses.update(a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith('127.'))
        except OSError:pass
        return [f'http://{a}:{self.port}' for a in sorted(addresses,key=lambda a:a=='127.0.0.1')]
    def stop(self):
        if self.server:self.server.should_exit=True

def install_host_routes(app,manager,ui_dist):
    """Only installed on the existing loopback control app."""
    from rpg_gateway.settings import config_dir
    from rpg_gateway import build_router
    from .tunnel_connections import RoomConnections,origin
    connections=RoomConnections(config_dir()/'multiplayer-connections.json')
    holder={};guard=threading.Lock()
    def local(request):
        if request.client and request.client.host not in ('127.0.0.1','::1','testclient'):raise PartyError('请在房主本机操作',403)
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).hostname not in ('127.0.0.1','localhost','tauri.localhost'):raise PartyError('请在房主应用操作',403)
    def host():
        with guard:
            if not holder:
                parties=PartyManager(config_dir()/'multiplayer',lambda:build_router(manager.settings.model_copy(deep=True)))
                parties.rebase_assets(manager.builtin_dir)
                holder['host']=PartyHost(parties,ui_dist,port=int(__import__('os').environ.get('RPG_PARTY_PORT','8790')))
                if any(r['phase']!='closed' for r in parties.rooms.values()):holder['host'].start()
            return holder['host']
    @app.get('/api/multiplayer/host/status')
    def status(request:Request):
        local(request)
        with manager.lock:
            return {'title':manager.session.pack.manifest.title,'items':[{'id':i.id,'name':i.name} for i in manager.session.pack.items],
                'addresses':host().addresses(),'running':bool(host().server and host().server.started),
                'rooms':[{'id':r['id'],'title':r['title'],'round':r['round'],'phase':r['phase']} for r in host().parties.rooms.values() if r['phase']!='closed']}
    @app.post('/api/multiplayer/host/rooms/{room_id}/resume')
    def resume(request:Request,room_id:str):
        local(request);service=host();service.start()
        with service.parties.lock:
            room=service.parties._room(room_id)
            if room['phase']=='closed':raise PartyError('该房间已关闭',409)
            owner=room['players'][room['owner']]
            return {'server_url':f'http://127.0.0.1:{service.port}','room_id':room_id,'player_id':owner['id'],'token':service.parties._token(room,owner)}
    @app.get('/api/multiplayer/client-session')
    def saved_client(request:Request):
        local(request);path=config_dir()/'multiplayer-client-session.json'
        try:return {'session':ClientSession.model_validate_json(path.read_text(encoding='utf-8')).model_dump(mode='json')}
        except (OSError,ValueError):return {'session':None}
    @app.post('/api/multiplayer/client-session')
    def save_client(request:Request,body:ClientSave):
        local(request);path=config_dir()/'multiplayer-client-session.json'
        if body.session:
            from urllib.parse import urlsplit
            url=urlsplit(body.session.server_url)
            if url.scheme not in ('http','https') or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise PartyError('联机地址无效')
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix(f'.{threading.get_ident()}.{time.time_ns()}.tmp');temporary.write_text(body.session.model_dump_json(),encoding='utf-8');temporary.replace(path)
            try:path.chmod(0o600)
            except OSError:pass
        else:path.unlink(missing_ok=True)
        return {'ok':True}
    @app.post('/api/multiplayer/host/rooms')
    def create(request:Request,body:HostRoom):
        local(request);service=host();service.start()
        with manager.lock:
            result=service.parties.create(manager.session.pack,manager.pack_dir,manager.builtin_dir/'new-game',body.name,body.capacity,body.unique_items,body.request_id)
        return {**result,'server_url':f'http://127.0.0.1:{service.port}','addresses':service.addresses()}
    @app.post('/api/multiplayer/connections')
    def select_connection(request:Request,body:ConnectionSelection):
        local(request);return {'server_url':connections.select(body.server_url)}
    @app.api_route('/api/multiplayer/relay',methods=['GET','POST','PUT'])
    async def relay(request:Request,target:str):
        """Bridge only to explicitly selected room origins; keep Android HTTP policy."""
        local(request)
        import re,urllib.request,urllib.error
        from urllib.parse import urlsplit
        url=urlsplit(target)
        selected_origin=origin(target)
        if not connections.permits(target):raise PartyError('请先在加入界面指定并连接此房主地址',403)
        path=url.path
        if not re.fullmatch(r'/api/(party/health|rooms/join|rooms/room_[a-f0-9]{24}/(state|intent|ready|generate|retry|leave|cancel|undo|undo/vote|events|sheet|pending/pending_[a-f0-9]{24}/dismiss|assets/ui/[A-Za-z0-9_./%+~-]+))',path) or '..' in path:raise PartyError('转接路径不属于联机接口',403)
        payload=await request.body()
        if len(payload)>65536:raise PartyError('联机请求过大',413)
        headers={'User-Agent':USER_AGENT,'Content-Type':'application/json','ngrok-skip-browser-warning':'true'}
        if request.headers.get('authorization'):headers['Authorization']=request.headers['authorization']
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        def open_remote():
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            return opener.open(urllib.request.Request(selected_origin+url.path,data=payload if request.method!='GET' else None,headers=headers,method=request.method),timeout=30)
        try:upstream=await asyncio.to_thread(open_remote)
        except urllib.error.HTTPError as exc:
            data=exc.read(65536);exc.close();return Response(data,status_code=exc.code,media_type='application/json')
        except (OSError,ValueError):raise PartyError('无法连接房主，请检查穿透是否在线、房主域名和对外端口是否正确',502) from None
        content_type=upstream.headers.get_content_type()
        if content_type=='text/event-stream':
            def stream():
                try:
                    while True:
                        chunk=upstream.readline(262144)
                        if not chunk:break
                        yield chunk
                finally:upstream.close()
            return StreamingResponse(stream(),media_type=content_type,headers={'Cache-Control':'no-cache'})
        try:data=await asyncio.to_thread(upstream.read,8*1024*1024+1)
        finally:upstream.close()
        if len(data)>8*1024*1024:raise PartyError('联机资源过大',413)
        return Response(data,media_type=content_type,headers={'Cache-Control':'no-store'})
    # PartyError only; existing single-player exception handling stays intact.
    @app.exception_handler(PartyError)
    async def party_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=exc.status)
    return holder
