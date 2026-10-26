"""Explicit, local-device selection of room-server origins for HTTP bridging."""
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress,json,threading,urllib.request
from rpg_core.party import PartyError
from .http_identity import USER_AGENT

def origin(value):
    try:
        url=urlsplit(value);port=url.port;host=url.hostname
        if url.scheme not in ('http','https') or not host or url.username or url.password or url.query or url.fragment:raise ValueError()
        if port is not None and not 1<=port<=65535:raise ValueError()
        host=host.encode('idna').decode().lower()
        if ':' in host:host='['+host+']'
        base=url.scheme+'://'+host
        if port is not None and port!=({'http':80,'https':443}[url.scheme]):base+=':'+str(port)
        return base
    except (ValueError,UnicodeError):raise PartyError('房主地址无效，请使用HTTP或HTTPS地址',400) from None

def legacy_lan(value):
    url=urlsplit(value)
    try:
        ip=ipaddress.ip_address(url.hostname or '')
        return url.port==8790 and any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8'))
    except ValueError:return False

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def opener():return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

class RoomConnections:
    """Only the device's loopback control API can add an explicitly chosen host."""
    def __init__(self,path):self.path=Path(path);self.lock=threading.RLock()
    def _origins(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            return {origin(v) for v in data if isinstance(v,str)} if isinstance(data,list) else set()
        except (OSError,ValueError):return set()
    def permits(self,value):
        with self.lock:return legacy_lan(value) or origin(value) in self._origins()
    def select(self,value):
        url=urlsplit(value);base=origin(value)
        if url.path not in ('','/'):raise PartyError('请填写房主服务根地址，不要附加页面路径',400)
        # Fixed, credential-free handshake before trusting this specific origin.
        request=urllib.request.Request(base+'/api/party/health',headers={'User-Agent':USER_AGENT,'ngrok-skip-browser-warning':'true'})
        try:
            with opener().open(request,timeout=10) as response:data=json.loads(response.read(8192))
            if data.get('mode')!='cooperative' or data.get('protocol')!=1:raise ValueError()
        except Exception:raise PartyError('该地址未返回联机服务，请确认穿透映射到房主的8790端口',502) from None
        with self.lock:
            entries=self._origins()
            if base not in entries and len(entries)>=64:raise PartyError('已保存64个房主地址，请清理连接配置后重试',409)
            entries.add(base);self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(sorted(entries)),encoding='utf-8');temporary.replace(self.path)
        return base
