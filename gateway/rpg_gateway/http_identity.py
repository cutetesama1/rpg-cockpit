"""Application HTTP identity shared by JSON, SSE, audio and room requests."""
from __future__ import annotations
import re
from typing import Mapping

USER_AGENT = 'RPG-Cockpit/0.992'

def api_headers(api_key: str = '', *, accept: str = 'application/json', content_type: str | None = 'application/json') -> dict[str, str]:
    headers = {'User-Agent': USER_AGENT, 'Accept': accept}
    if content_type is not None:
        headers['Content-Type'] = content_type
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers

def cloudflare_1010_hint(status: int, body: str, headers: Mapping[str, str]) -> str:
    """Explain an explicit 1010 without rendering remote HTML or echoed secrets."""
    if status < 400:
        return ''
    source = (str(headers.get('Server', '')) + ' ' + body).casefold()
    marker = str(headers.get('cf-error-type', ''))
    if not ('cloudflare' in source or marker == '1010'):
        return ''
    if not (marker == '1010' or re.search(r'(?<!\d)1010(?!\d)', body)):
        return ''
    message = ('Cloudflare 1010：网关按客户端标识拒绝了请求，并非已确认的 API Key 错误。'
               f'当前 User-Agent 为 {USER_AGENT}；请由网关管理员检查 Browser Integrity Check / WAF 规则，或提供允许服务端调用的 API 地址。')
    ray = str(headers.get('CF-Ray', ''))
    if re.fullmatch(r'[A-Za-z0-9-]{1,100}', ray):
        message += f' CF-Ray: {ray}'
    return message
