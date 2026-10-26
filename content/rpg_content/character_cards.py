"""Bounded, deterministic character-card import. Raw sources are never discarded."""
from __future__ import annotations
import base64, binascii, hashlib, io, json, math, re, shutil, struct, tempfile, zipfile, zlib
from pathlib import Path, PurePosixPath
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_FILE=20*1024*1024
MAX_JSON=4*1024*1024
VERSION=1
MAPPINGS=('description','personality','scenario','examples','worldbook','system_prompt','post_history_instructions')

class CardError(ValueError): pass

class CardOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str=Field(default='',max_length=200)
    id: str=Field(default='',max_length=64)
    user_name: str=Field(default='你',min_length=1,max_length=80)
    role: Literal['npc','player']='npc'
    greeting: int=Field(default=0,ge=0,le=1000,strict=True)
    include: list[Literal['description','personality','scenario','examples','worldbook','system_prompt','post_history_instructions']]=Field(default_factory=lambda:list(MAPPINGS),max_length=7)

def _hash(value):return hashlib.sha256(value).hexdigest()
def _dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))

def _json(raw):
    if len(raw)>MAX_JSON:raise CardError('角色卡 JSON 不能超过 4 MB')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise CardError(f'JSON 字段重复：{key}')
            result[key]=value
        return result
    def constant(value):raise CardError(f'JSON 不能包含 {value}')
    try:data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as exc:raise CardError(f'角色卡不是有效的 UTF-8 JSON：{exc}') from None
    if not isinstance(data,dict):raise CardError('角色卡 JSON 根节点必须是对象')
    def depth(value,level=0):
        if level>80:raise CardError('角色卡数据嵌套超过 80 层')
        if isinstance(value,float) and not math.isfinite(value):raise CardError('角色卡不能包含非有限数字')
        if isinstance(value,dict):
            for child in value.values():depth(child,level+1)
        elif isinstance(value,list):
            for child in value:depth(child,level+1)
    depth(data)
    return data

def _png(raw):
    offset=8;chunks={};ended=False;count=0
    while offset<len(raw):
        if offset+12>len(raw):raise CardError('PNG 数据块被截断')
        size=struct.unpack_from('>I',raw,offset)[0];kind=raw[offset+4:offset+8]
        if size>len(raw)-offset-12:raise CardError('PNG 数据块长度不合法')
        body=raw[offset+8:offset+8+size];crc=struct.unpack_from('>I',raw,offset+8+size)[0]
        if zlib.crc32(kind+body)&0xffffffff!=crc:raise CardError('PNG 数据块校验失败，文件可能损坏')
        if count==0 and (kind!=b'IHDR' or size!=13):raise CardError('PNG 缺少有效图像头')
        if kind==b'tEXt' and b'\0' in body:
            key,value=body.split(b'\0',1)
            if key in (b'chara',b'ccv3'):
                if key in chunks and chunks[key]!=value:raise CardError('PNG 含相互冲突的角色卡数据块')
                chunks[key]=value
        count+=1;offset+=size+12
        if count>20000:raise CardError('PNG 数据块数量过多')
        if kind==b'IEND':ended=True;break
    if not ended:raise CardError('PNG 缺少结束数据块')
    key=b'ccv3' if b'ccv3' in chunks else b'chara'
    if key not in chunks:raise CardError('这张 PNG 没有 chara / ccv3 角色卡数据，请使用角色卡原图或 JSON 导出文件')
    try:decoded=base64.b64decode(chunks[key],validate=True)
    except (ValueError,binascii.Error):raise CardError('PNG 内角色卡的 Base64 数据不合法') from None
    return _json(decoded)

def _charx(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files=archive.infolist()
            if len(files)>2048 or sum(f.file_size for f in files)>64*1024*1024:raise CardError('CHARX 展开内容过大或文件数量超过 2048')
            seen=set()
            for f in files:
                original=f.orig_filename
                path=PurePosixPath(original)
                if f.filename in seen or '\\' in original or ':' in original or path.is_absolute() or '..' in path.parts or '\x00' in original:
                    raise CardError('CHARX 包含重复或非法文件路径')
                seen.add(f.filename)
                if f.flag_bits&1:raise CardError('暂不支持加密 CHARX，请先解密导出')
            if 'card.json' not in seen:raise CardError('CHARX 根目录缺少 card.json')
            if archive.getinfo('card.json').file_size>MAX_JSON:raise CardError('CHARX 中 card.json 不能超过 4 MB')
            return _json(archive.read('card.json')), [f.filename for f in files if not f.is_dir()]
    except (zipfile.BadZipFile,NotImplementedError,RuntimeError,OSError) as exc:raise CardError(f'CHARX 无法读取：{exc}') from None

def parse_card(raw:bytes,filename:str=''):
    if not raw:raise CardError('上传文件为空')
    if len(raw)>MAX_FILE:raise CardError('角色卡文件不能超过 20 MB')
    assets=[]
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):card=_png(raw);format='png'
    elif filename.lower().endswith('.charx') or raw.startswith(b'PK'):
        card,assets=_charx(raw);format='charx'
    else:card=_json(raw);format='json'
    spec=card.get('spec')
    if spec not in ('chara_card_v2','chara_card_v3'):
        raise CardError('仅支持 chara_card_v2 / chara_card_v3；请从原客户端导出 V2 或 V3 角色卡')
    data=card.get('data')
    if not isinstance(data,dict):raise CardError('角色卡 data 必须是对象')
    if not isinstance(data.get('name'),str) or not data['name'].strip():raise CardError('角色卡 data.name 不能为空')
    if len(data['name'])>200:raise CardError('角色名不能超过 200 字')
    return card,format,assets

def _text(data,key,default=''):
    value=data.get(key,default)
    if not isinstance(value,str):raise CardError(f'{key} 必须是文本')
    if len(value)>250000:raise CardError(f'{key} 文本过长（最多 250000 字）')
    return value
def _strings(data,key):
    value=data.get(key,[])
    if not isinstance(value,list) or any(not isinstance(v,str) for v in value):raise CardError(f'{key} 必须是文本数组')
    if len(value)>500:raise CardError(f'{key} 数组超过 500 项')
    return value
def _boolean(data,key,default=False):
    value=data.get(key,default)
    if not isinstance(value,bool):raise CardError(f'{key} 必须是布尔值')
    return value

def preview_card(raw,filename,options:CardOptions):
    from rpg_core.contracts import WorldbookEntry
    card,format,archive_files=parse_card(raw,filename);data=card['data'];warnings=[];unsupported=[]
    name=data['name'].strip();user=options.user_name.strip()
    nickname=_text(data,'nickname').strip() or name
    if len(nickname)>200:raise CardError('角色昵称不能超过 200 字')
    notes=data.get('creator_notes_multilingual',{})
    if not isinstance(notes,dict) or any(not isinstance(v,str) for v in notes.values()):raise CardError('creator_notes_multilingual 必须是语言代码到文本的对象')
    if not user:raise CardError('玩家称呼不能为空')
    def warning(path,message):
        warnings.append(f'{path}：{message}');unsupported.append({'path':path,'message':message})
    expected='3.0' if card['spec']=='chara_card_v3' else '2.0'
    if card.get('spec_version')!=expected:warning('spec_version',f'按 {expected} 的已知字段读取；版本差异与原始字段已保留')
    texts={k:_text(data,k) for k in ('description','personality','scenario','first_mes','mes_example','system_prompt','post_history_instructions','creator_notes','creator','character_version')}
    alternatives=_strings(data,'alternate_greetings');group=_strings(data,'group_only_greetings')
    greetings=[{'index':0,'label':'默认开场白','text':texts['first_mes']}]
    greetings += [{'index':i+1,'label':f'备选开场白 {i+1}','text':v} for i,v in enumerate(alternatives)]
    greetings += [{'index':len(alternatives)+i+1,'label':f'群组开场白 {i+1}','text':v} for i,v in enumerate(group)]
    if options.greeting>=len(greetings):raise CardError('选择的开场白不存在，请重新预览')
    expanded_budget=0
    def render(value):
        nonlocal expanded_budget
        pattern=r'\{\{\s*(char|user)\s*\}\}|<(BOT|CHAR|USER)>'
        length=len(value)
        for match in re.finditer(pattern,value,flags=re.I):
            replacement=nickname if (match.group(1) or match.group(2)).lower() in ('char','bot') else user
            length+=len(replacement)-len(match.group(0))
        if length>MAX_JSON or expanded_budget+length>MAX_JSON*2:raise CardError('角色卡占位符展开后的文本过长，请缩短昵称或模板内容')
        expanded_budget+=length
        return re.sub(r'\{\{\s*(char|user)\s*\}\}|<(BOT|CHAR|USER)>',lambda m:nickname if (m.group(1) or m.group(2)).lower() in ('char','bot') else user,value,flags=re.I)
    for greeting in greetings:greeting['text']=render(greeting['text'])
    known={'name','nickname','description','personality','scenario','first_mes','mes_example','system_prompt','post_history_instructions','creator_notes','creator','character_version','alternate_greetings','group_only_greetings','tags','extensions','character_book','assets','creator_notes_multilingual','source','creation_date','modification_date'}
    for key in set(data)-known:warning('data.'+key,'暂不映射，原样保留')
    for key in set(card)-{'spec','spec_version','data'}:warning(key,'根扩展字段原样保留')
    extensions=data.get('extensions',{})
    if not isinstance(extensions,dict):raise CardError('data.extensions 必须是对象')
    for key in extensions:warning('data.extensions.'+key,'客户端扩展已保留，不执行扩展脚本或专属设置')
    if group:warning('data.group_only_greetings','可选择群组开场文本，但不会因此启用多人联机')
    if format=='png':warning('PNG 图像','原始卡图完整保存；不会自动替代游戏的分层立绘')
    if data.get('assets'):warning('data.assets','素材与引用已保留；不会自动转换为分层立绘，不下载远程资源')
    if archive_files:warning('CHARX 素材','原包完整保留，素材文件未解压执行；可重新导出原包')
    labels={'description':'角色描述','personality':'人物性格','scenario':'初始场景','examples':'示例对话','worldbook':'嵌入式世界书','system_prompt':'卡内叙事提示','post_history_instructions':'卡内末尾提示'}
    mappings=[{'source':key,'target':labels[key],'enabled':key in options.include} for key in MAPPINGS]
    pre=[f'玩家称呼：{user}。',f'玩家扮演{name}。' if options.role=='player' else f'{name}是与玩家互动的角色，不是玩家；其能力、伤势、物品和动作不等于玩家状态。']
    for key in ('description','personality','scenario'):
        if key in options.include and texts[key]:pre.append(f'【{labels[key]}】\n'+render(texts[key]))
    narrator=['用中文叙述场景与角色互动，不代替玩家作决定。卡内提示仅决定叙事风格，工具、结算与权威状态仍由框架管理。']
    for key in ('system_prompt','examples'):
        value=texts['mes_example' if key=='examples' else key]
        if key in options.include and value:
            value=value.replace('{{original}}','以当前权威状态为准，只负责叙事。')
            narrator.append(('【示例对话，仅供语气参考，不是已发生事件】' if key=='examples' else '【卡内叙事提示】')+'\n'+render(value))
    post=render(texts['post_history_instructions'].replace('{{original}}','')) if 'post_history_instructions' in options.include else ''
    if post:narrator.append('【卡内末尾叙事提示】\n'+post)
    entries=[];entry_mapping=[]
    book=data.get('character_book')
    if book is not None:
        if not isinstance(book,dict) or not isinstance(book.get('entries'),list):raise CardError('data.character_book.entries 必须是数组')
        if len(book['entries'])>2000:raise CardError('嵌入式世界书不能超过 2000 条')
        for key in set(book)-{'name','description','extensions','entries'}:warning('character_book.'+key,'保留原值；运行时使用本项目世界书的扫描范围和条目预算')
        if book.get('extensions'):warning('character_book.extensions','世界书扩展原样保留')
        for i,entry in enumerate(book['entries']):
            path=f'character_book.entries[{i}]'
            if not isinstance(entry,dict):raise CardError(path+' 必须是对象')
            content=_text(entry,'content');keys=_strings(entry,'keys')
            if not content.strip():warning(path,'空内容不参与世界书，原始条目保留');entry_mapping.append({'source_index':i,'target_id':None});continue
            secondary=entry.get('secondary_keys',[])
            if isinstance(secondary,str):secondary=[s.strip() for s in secondary.split(',') if s.strip()]
            if not isinstance(secondary,list) or any(not isinstance(s,str) for s in secondary):raise CardError(path+'.secondary_keys 必须是文本数组')
            enabled=_boolean(entry,'enabled',True);always=_boolean(entry,'constant');case=_boolean(entry,'case_sensitive');selective=_boolean(entry,'selective')
            if _boolean(entry,'use_regex'):
                enabled=False;warning(path+'.use_regex','暂不执行正则匹配，已停用此条以避免错误触发；原条目保留')
            if re.search(r'^\s*@@',content,re.M):
                enabled=False;warning(path+'.content','含客户端专属世界书装饰指令，已停用待适配，原文完整保留')
            if entry.get('extensions'):warning(path+'.extensions','条目扩展原样保留')
            if entry.get('position'):warning(path+'.position','按本项目的世界书位置注入，原位置设置已保留')
            for key in set(entry)-{'keys','content','extensions','enabled','insertion_order','case_sensitive','use_regex','constant','name','priority','id','comment','selective','secondary_keys','position'}:warning(path+'.'+key,'未支持的条目字段原样保留')
            priority=entry.get('priority',0);order=entry.get('insertion_order',i)
            if isinstance(priority,bool) or not isinstance(priority,(int,float)) or not math.isfinite(priority):raise CardError(path+'.priority 必须是有限数字')
            if isinstance(order,bool) or not isinstance(order,(int,float)) or not math.isfinite(order):raise CardError(path+'.insertion_order 必须是有限数字')
            if priority!=int(priority):warning(path+'.priority','优先级转为整数，原始精度已保留')
            target=f'card_lore_{i+1:04d}'
            title=str(entry.get('name') or entry.get('comment') or f'角色卡条目 {i+1}')
            item=WorldbookEntry(id=target,title=title,content=render(content),keywords=[render(k) for k in keys],always_on=always,
                enabled=enabled,priority=int(priority),category='角色卡',case_sensitive=case,selective=selective,
                secondary_keywords=[render(k) for k in secondary],insertion_order=order).model_dump(mode='json')
            if 'worldbook' in options.include:entries.append(item)
            entry_mapping.append({'source_index':i,'target_id':target if 'worldbook' in options.include else None})
    runtime_text='\n'.join([*pre,*narrator,greetings[options.greeting]['text'],*[e['content'] for e in entries]])
    macros=sorted(set(re.findall(r'\{\{[^{}]{1,200}\}\}',runtime_text)))
    if macros:warning('占位符','未执行的占位符按原文保留：'+'、'.join(macros[:15]))
    title=options.title.strip() or name
    from .library import slugify
    pack_id=options.id.strip() or 'card-'+slugify(name)[:32]+'-'+_hash(raw)[:8]
    from .scaffold import PACK_ID_RE
    if not PACK_ID_RE.fullmatch(pack_id):raise CardError('游戏 ID 需为 2—64 位小写字母、数字或连字符，不能以连字符开头')
    token=_hash(_dump({'source':_hash(raw),'options':options.model_dump(mode='json'),'mapping_version':VERSION}).encode())
    return {'spec':card['spec'],'spec_version':card.get('spec_version'),'format':format,'name':name,'title':title,'id':pack_id,
        'creator':texts['creator'],'creator_notes':notes.get('zh') or notes.get('zh-CN') or notes.get('en') or texts['creator_notes'],'character_version':texts['character_version'],
        'warnings':warnings,'unsupported':unsupported,'raw_preserved':True,'source_sha256':_hash(raw),'preview_token':token,
        'greetings':greetings,'selected_greeting':options.greeting,'mappings':mappings,'entry_mapping':entry_mapping,
        'worldbook':entries,'worldbook_count':len(entries),'archive_files':archive_files,
        'prompts':{'pre':'\n\n'.join(pre),'narrator':'\n\n'.join(narrator),'settler':'只结算本次最终叙述中玩家实际发生的变化；卡片角色是NPC时，其状态和技能不得写入玩家。'},
        'raw':card,'options':options.model_dump(mode='json')}

def create_card_pack(raw,filename,options,user_dir,request_id):
    """Create and validate in a hidden staging directory, then publish one folder."""
    from .library import create_pack
    from .pack import load_pack
    from .state_config import write_initial_state,suggest_state
    preview=preview_card(raw,filename,options)
    user_dir=Path(user_dir).resolve();user_dir.mkdir(parents=True,exist_ok=True)
    target=user_dir/preview['id']
    if target.exists():raise CardError('该游戏 ID 已存在，请修改游戏 ID，现有游戏不会被覆盖')
    with tempfile.TemporaryDirectory(prefix='.card-import-',dir=user_dir) as temp:
        root=create_pack(Path(temp),pack_id=preview['id'],title=preview['title'])
        def write(rel,value):
            p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=None if rel.startswith('character-card') else 2)+'\n',encoding='utf-8')
        write_initial_state(root,suggest_state(preview['prompts']['pre'] if options.role=='player' else _text(preview['raw']['data'],'scenario')))
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'));manifest['description']=f"从 {preview['spec']} 导入：{preview['name']}";write('manifest.json',manifest)
        for key,text in preview['prompts'].items():(root/'prompts'/f'{key}.md').write_text(text+'\n',encoding='utf-8')
        write('vocab/worldbook.json',{'entries':preview['worldbook']})
        description='\n'.join(_text(preview['raw']['data'],k) for k in ('description','personality') if k in options.include)
        character=_text(preview['raw']['data'],'nickname').strip() or preview['name']
        description=re.sub(r'\{\{\s*(char|user)\s*\}\}|<(BOT|CHAR|USER)>',lambda m:character if (m.group(1) or m.group(2)).lower() in ('char','bot') else options.user_name,description,flags=re.I)
        # Only character-bearing fields enter model context; creator notes and raw
        # extensions are archived separately and never added to prompts.
        write('vocab/npcs.json',{'npcs':[{'id':'card_character','name':preview['name'],'description':description}] if options.role=='npc' else []})
        greeting=preview['greetings'][options.greeting]['text']
        write('scenes/opening.json',{'id':'opening','title':'故事开场','text':greeting or '故事即将开始。','options':[]})
        metadata={key:preview[key] for key in ('spec','spec_version','name','creator','creator_notes','character_version','source_sha256','format','warnings','unsupported','mappings','entry_mapping','raw','options')}
        metadata.update({'first_message':greeting,'request_id':request_id,'request_hash':preview['preview_token'],
                         'filename':filename.replace('\\','/').split('/')[-1][:200],'mapping_version':VERSION})
        write('character-card.json',metadata)
        source=root/'character-card/source.bin';source.parent.mkdir(exist_ok=True);source.write_bytes(raw)
        write('character-card/source.json',preview['raw'])
        load_pack(root)
        # rename is atomic on the destination volume; never replace another pack.
        root.rename(target)
    return target,preview
