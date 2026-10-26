"""Persistent cooperative rooms. Network calls never hold the room state lock."""
from __future__ import annotations
import copy,hashlib,hmac,json,math,re,secrets,sqlite3,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .contracts import ContentPack,SkillSpec,ToolCall
from .guardrails import ToolExecutor
from .portrait import portrait_changes
from .clothing import wardrobe_snapshot
from .portrait import portrait_snapshot
from .appearance_catalog import field_views
from .scenes import unmet_conditions
from .party_contracts import PartyIntent,PartyProposal,NARRATOR_PROMPT,SETTLER_PROMPT

def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def uid(prefix):return prefix+'_'+secrets.token_hex(12)

class PartyError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status

def response_data(response):
    raw=response.raw or ''
    try:
        outer=json.loads(raw)
        if isinstance(outer,dict) and outer.get('choices'):
            raw=outer['choices'][0]['message'].get('content') or ''
        elif isinstance(outer,dict) and ('operations' in outer or 'narrative' in outer):return outer
    except (ValueError,KeyError,TypeError):pass
    if response.narrator and not raw:raw=response.narrator.narrative
    if raw:
        start=raw.find('{');end=raw.rfind('}')
        if start>=0 and end>start:
            try:return json.loads(raw[start:end+1])
            except ValueError:pass
    if response.narrator:return {'narrative':response.narrator.narrative,'options':[]}
    raise PartyError('模型未返回有效结果')

class PartyManager:
    def __init__(self,directory,router_factory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.db=self.directory/'rooms.sqlite3';self.router_factory=router_factory
        self.lock=threading.RLock();self.changed=threading.Condition(self.lock)
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='rpg-party')
        secret_file=self.directory/'session-secret'
        if not secret_file.exists():secret_file.write_bytes(secrets.token_bytes(32))
        self.secret=secret_file.read_bytes()
        try:secret_file.chmod(0o600)
        except OSError:pass
        with self._db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS packs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,room TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS room_events ON events(room,seq);
CREATE TABLE IF NOT EXISTS snapshots(room TEXT NOT NULL,round INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(room,round));''')
            self.rooms={row[0]:json.loads(row[1]) for row in db.execute('SELECT id,data FROM rooms')}
        self.packs={};self.closed=False
        for room in self.rooms.values():
            room.setdefault('opening_generated',bool(room['round'] or room['history'] or room.get('task')))
            room.setdefault('opening',None)
            if room.get('task'):room['task'].setdefault('kind','turn')
            if room['phase'] in ('frozen','narrating','settling'):
                room['phase']='failed';room['task']['status']='failed';room['task']['error']='房主服务已重启，请重试未完成阶段。'
                self._save(room,'round.recovered',{})

    def _db(self):return sqlite3.connect(self.db,timeout=20)
    def rebase_assets(self,builtin_dir):
        """Bundled EXE extraction paths change at every launch."""
        builtin_dir=Path(builtin_dir).resolve()
        with self.lock:
            for room in self.rooms.values():
                previous=(room['asset_root'],room['fallback_root'])
                if not Path(room['asset_root']).is_dir():
                    candidate=(builtin_dir/self._pack(room).manifest.id).resolve()
                    if candidate.is_relative_to(builtin_dir) and candidate.is_dir():room['asset_root']=str(candidate)
                room['fallback_root']=str(builtin_dir/'new-game')
                if previous!=(room['asset_root'],room['fallback_root']):self._save(room,'assets.rebased',{})
    def _save(self,room,kind,payload,before=None):
        room['revision']+=1
        public={'revision':room['revision'],'round':room['round'],**payload}
        with self._db() as db:
            if before is not None:db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)',(room['id'],room['round'],encoded(before)))
            db.execute('INSERT OR REPLACE INTO rooms VALUES(?,?)',(room['id'],encoded(room)))
            db.execute('INSERT INTO events(room,kind,data) VALUES(?,?,?)',(room['id'],kind,encoded(public)))
        self.changed.notify_all() if self.lock._is_owned() else None

    def _pack(self,room):
        key=room['pack_key']
        if key not in self.packs:
            with self._db() as db:row=db.execute('SELECT data FROM packs WHERE id=?',(key,)).fetchone()
            if not row:raise PartyError('房间世界定义缺失',500)
            self.packs[key]=ContentPack.model_validate(json.loads(row[0]))
        return self.packs[key]

    def _room(self,room_id):
        room=self.rooms.get(room_id)
        if not room:raise PartyError('房间不存在',404)
        return room

    def _token(self,room,player):return hmac.new(self.secret,(room['id']+':'+player['id']+':'+player['session']).encode(),hashlib.sha256).hexdigest()
    def _auth(self,room,token):
        if not token:raise PartyError('请先加入房间',401)
        for player in room['players'].values():
            if player['active'] and hmac.compare_digest(self._token(room,player),token):return player
        raise PartyError('会话无效或你已离开房间',403)
    def _host(self,room,player):
        if player['id']!=room['owner']:raise PartyError('只有房主可以操作',403)
    def _collecting(self,room):
        if room['phase']!='collecting':raise PartyError('当前回合已冻结或房间暂不可操作',409)
    def _round(self,room,token):
        if token!=room['round_token']:raise PartyError('回合已改变，请刷新后重新提交',409)
    def _seen(self,room,player,request_id,body):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,120}',request_id):raise PartyError('请求编号无效')
        key=digest([player['id'],request_id]);item=room['receipts'].get(key)
        if item:
            if item['hash']!=digest(body):raise PartyError('请求编号已用于不同内容',409)
            if item['epoch']!=room['epoch']:raise PartyError('请求属于已撤回的房间版本',409)
        return key,item
    def _receipt(self,room,key,body,**extra):
        room['receipts'][key]={'hash':digest(body),'epoch':room['epoch'],**extra}
        while len(room['receipts'])>600:del room['receipts'][next(iter(room['receipts']))]

    def _new_player(self,room,name):
        name=name.strip()
        if not name or len(name)>40 or any(p['active'] and p['name']==name for p in room['players'].values()):raise PartyError('姓名为空、过长或与队友重复')
        pack=self._pack(room)
        player={'id':uid('actor'),'name':name,'session':secrets.token_hex(16),'active':True,'slot':len(room['players']),
            'state':{k:v for k,v in pack.state.defaults().items() if k not in room['world']['state']},'inventory':{},
            'skills':[s.model_dump(mode='json') for s in pack.skills],'cooldowns':{},'intent':None,'intent_revision':0,'ready':False}
        room['players'][player['id']]=player;return player

    def create(self,pack,asset_root,fallback_root,name,capacity=4,unique_items=(),request_id=None):
        if capacity not in (2,3,4):raise PartyError('首版支持2—4人')
        if not set(unique_items)<={i.id for i in pack.items}:raise PartyError('唯一物品不在当前世界目录')
        with self.lock:
            if request_id:
                for r in self.rooms.values():
                    if r.get('create_request_id')==request_id:
                        if r.get('create_hash')!=digest([pack.model_dump(mode='json'),name,capacity,list(unique_items)]):raise PartyError('建房请求编号已用于不同内容',409)
                        p=r['players'][r['owner']]
                        return {'room_id':r['id'],'player_id':p['id'],'token':self._token(r,p),'invite_code':r['invite']}
            if sum(r['phase']!='closed' for r in self.rooms.values())>=20:raise PartyError('开放房间已达20个，请先关闭旧房间')
            snapshot=pack.model_dump(mode='json');key=digest(snapshot)
            with self._db() as db:db.execute('INSERT OR IGNORE INTO packs VALUES(?,?)',(key,encoded(snapshot)))
            self.packs[key]=pack.model_copy(deep=True)
            shared={f.id:f.default for f in pack.state.fields if f.group in ('flags','world') or f.id.startswith('flag_')}
            for field in pack.state.resource_bindings.values():shared.pop(field,None)
            room={'id':uid('room'),'title':pack.manifest.title,'pack_key':key,'asset_root':str(Path(asset_root).resolve()),'fallback_root':str(Path(fallback_root).resolve()),
                'capacity':capacity,'owner':'','phase':'collecting','round':0,'round_token':uid('round'),'epoch':uid('epoch'),'revision':0,
                'opening_generated':False,'opening':None,'players':{},'world':{'state':shared,'scene':pack.opening.id,'facts':{}},'history':[],'pending':[],'receipts':{},'joins':{},'undo':None,'task':None,
                'invite':secrets.token_urlsafe(12),'invite_expires':time.time()+86400,'unique_items':list(unique_items)}
            room['create_request_id']=request_id;room['create_hash']=digest([snapshot,name,capacity,list(unique_items)])
            owner=self._new_player(room,name);room['owner']=owner['id'];self.rooms[room['id']]=room
            self._save(room,'room.created',{})
            return {'room_id':room['id'],'player_id':owner['id'],'token':self._token(room,owner),'invite_code':room['invite']}

    def join(self,invite,name,request_id):
        with self.lock:
            room=next((r for r in self.rooms.values() if hmac.compare_digest(r['invite'],invite)),None)
            if not room or room['invite_expires']<time.time() or room['phase']=='closed':raise PartyError('邀请无效或已过期',403)
            nonce=digest([request_id,name])
            if nonce in room['joins']:
                p=room['players'][room['joins'][nonce]]
                if not p['active']:raise PartyError('原会话已离开，请使用新加入请求',409)
            else:
                if room['round']!=0 or room['phase']!='collecting' or room.get('opening_generated'):raise PartyError('首版只允许开局前加入',409)
                if len([p for p in room['players'].values() if p['active']])>=room['capacity']:raise PartyError('房间已满',409)
                if not re.fullmatch(r'[A-Za-z0-9_.:-]{16,120}',request_id):raise PartyError('加入请求编号无效')
                p=self._new_player(room,name);room['joins'][nonce]=p['id'];self._save(room,'member.joined',{'player_id':p['id'],'name':p['name']})
            return {'room_id':room['id'],'player_id':p['id'],'token':self._token(room,p)}

    def _public_player(self,room,p,viewer):
        pack=self._pack(room);fields=pack.state.by_id();mine=p['id']==viewer['id']
        state={k:v for k,v in p['state'].items() if mine or k in fields and (fields[k].display!='hidden' or fields[k].group in ('appearance','sprite'))}
        skills=[]
        if mine:
            for s in p['skills']:
                left=p['cooldowns'].get(s['id'],0);affordable=all(float(p['state'].get(k,0))>=v for k,v in s['cost'].items())
                skills.append({**s,'cooldown_remaining':left,'affordable':affordable,'available':not left and affordable,'blocked_reason':'冷却或资源不足' if left or not affordable else None})
        return {'id':p['id'],'name':p['name'],'active':p['active'],'owner':p['id']==room['owner'],'state':state,'skills':skills,
            'inventory':p['inventory'] if mine else None,'submitted':bool(p['intent']),'ready':p['ready'],'intent_revision':p['intent_revision'] if mine else None,'intent':p['intent'] if mine else None}

    def view(self,room_id,token):
        with self.lock:
            room=self._room(room_id);viewer=self._auth(room,token);pack=self._pack(room);task=room['task']
            with self._db() as db:cursor=db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE room=?',(room_id,)).fetchone()[0]
            return {'id':room_id,'title':room['title'],'capacity':room['capacity'],'owner_id':room['owner'],'me':viewer['id'],'phase':room['phase'],'round':room['round'],
                'round_token':room['round_token'],'revision':room['revision'],'cursor':cursor,'world':copy.deepcopy(room['world']),
                'players':[self._public_player(room,p,viewer) for p in room['players'].values() if p['active']],
                'fields':field_views(pack),'layout':pack.ui.model_dump(mode='json'),'history':copy.deepcopy(room['history']),
                'items':[{'id':i.id,'name':i.name} for i in pack.items],
                'scene_title':next((s.title for s in [pack.opening,*pack.scenes] if s.id==room['world']['scene']),room['world']['scene']),
                'opening_text':'','opening_generated':room.get('opening_generated',False),'opening':copy.deepcopy(room.get('opening')),
                'pending':copy.deepcopy(room['pending']) if viewer['id']==room['owner'] else [],'pending_count':len(room['pending']),
                'task':{k:copy.deepcopy(task[k]) for k in ('id','round','status','text','error','narration_complete','kind')} if task else None,
                'undo':copy.deepcopy(room['undo']),
                **({'invite_code':room['invite'],'invite_expires':room['invite_expires']} if viewer['id']==room['owner'] else {})}

    def intent(self,room_id,token,request_id,round_token,expected_intent_revision,intent):
        intent=PartyIntent.model_validate(intent).model_dump(mode='json')
        if not intent['text'].strip() and not intent['skills']:raise PartyError('请填写行动或选择技能')
        if len(set(intent['skills']))!=len(intent['skills']):raise PartyError('不能重复选择同一技能')
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);body=['intent',round_token,expected_intent_revision,intent];key,old=self._seen(room,p,request_id,body)
            if not old:
                self._collecting(room);self._round(room,round_token)
                if not room.get('opening_generated'):raise PartyError('请先由房主点击生成世界',409)
                if p['intent_revision']!=expected_intent_revision:raise PartyError('你的行动已更新，请刷新后重试',409)
                self._prepare_player(p,intent,self._pack(room))
                p['intent']=intent;p['intent_revision']+=1;p['ready']=False;self._receipt(room,key,body)
                self._save(room,'intent.updated',{'player_id':p['id']})
            return self.view(room_id,token)

    def ready(self,room_id,token,request_id,round_token,intent_revision,ready):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);body=['ready',round_token,intent_revision,ready];key,old=self._seen(room,p,request_id,body)
            if not old:
                self._collecting(room);self._round(room,round_token)
                if not room.get('opening_generated'):raise PartyError('请先由房主点击生成世界',409)
                if p['intent_revision']!=intent_revision or not p['intent']:raise PartyError('先提交并确认当前行动',409)
                p['ready']=bool(ready);self._receipt(room,key,body);self._save(room,'ready.changed',{'player_id':p['id'],'ready':p['ready']})
                active=[m for m in room['players'].values() if m['active']]
                if len(active)>=2 and all(m['ready'] for m in active):self._freeze(room)
            return self.view(room_id,token)

    def generate_opening(self,room_id,token,request_id):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._host(room,p)
            body=['opening'];key,old=self._seen(room,p,request_id,body)
            if old or room.get('opening_generated') or room.get('task') and room['task'].get('kind')=='opening':return self.view(room_id,token)
            self._collecting(room)
            if len([p for p in room['players'].values() if p['active']])<2:raise PartyError('请等待至少一名队友加入后再生成世界',409)
            self._receipt(room,key,body);self._freeze(room,opening=True)
            return self.view(room_id,token)

    def _prepare_player(self,p,intent,pack):
        work=copy.deepcopy({k:p[k] for k in ('state','inventory','skills','cooldowns')});payments={}
        skills={s['id']:s for s in p['skills']}
        for key in intent['skills']:
            skill=skills.get(key)
            if skill is None or p['cooldowns'].get(key,0):raise PartyError('技能不存在或尚在冷却')
            if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in skill['cost'].values()):raise PartyError('技能费用定义非法')
            for field,cost in skill['cost'].items():
                if field not in work['state'] or not isinstance(work['state'][field],(int,float)):raise PartyError('技能资源字段不属于本人')
                definition=pack.state.by_id()[field];left=work['state'][field]-cost
                if left<max(definition.min or 0,0):raise PartyError('所选技能累计资源不足')
                work['state'][field]=int(left) if definition.type=='int' else left;payments[field]=payments.get(field,0)+cost
        work['cooldowns']={k:max(0,v-1) for k,v in work['cooldowns'].items()}
        for key in intent['skills']:work['cooldowns'][key]=skills[key]['cooldown']
        return work,payments

    def _freeze(self,room,opening=False):
        pack=self._pack(room);active=sorted((p for p in room['players'].values() if p['active']),key=lambda p:p['slot'])
        prepared={};paid={};inputs=[]
        for p in active:
            intent={'text':'','modes':[],'skills':[]} if opening else p['intent']
            prepared[p['id']],paid[p['id']]=self._prepare_player(p,intent,pack)
            inputs.append({'actor_id':p['id'],'name':p['name'],**intent,'skill_names':[s['name'] for s in p['skills'] if s['id'] in intent['skills']]})
        before={'world':copy.deepcopy(room['world']),'players':{p['id']:{k:copy.deepcopy(p[k]) for k in ('state','inventory','skills','cooldowns')} for p in active}}
        task={'id':uid('task'),'kind':'opening' if opening else 'turn','round':0 if opening else room['round']+1,'status':'frozen','text':'','error':'','narration_complete':False,'inputs':inputs,
            'input_hash':digest(inputs),'prepared':prepared,'paid':paid,'before':before,'options':[],'usage':[]}
        room['task']=task;room['phase']='frozen';self._save(room,'round.frozen',{'task_id':task['id'],'inputs':inputs})
        self.pool.submit(self._run,room['id'],task['id'])

    def _executor(self,pack,player):
        return ToolExecutor(pack.state,{i.id for i in pack.items},{f.id for f in pack.flags},
            scenes={s.id:s for s in pack.scenes},skill_ids={s['id'] for s in player['skills']},wardrobe=pack.wardrobe,
            skill_catalog=pack.skill_catalog,catalog_mode=bool(pack.skill_catalog),known_skills=[SkillSpec.model_validate(s) for s in player['skills']])

    def _apply(self,room,working,op,narrative,delta):
        pack=self._pack(room);actor=op.actor_id;args=dict(op.args);name=op.name
        if op.evidence not in narrative:raise PartyError('证据不属于本轮正文')
        fields=pack.state.by_id()
        if actor=='world':
            if name=='record_fact':
                key=args.get('id');value=args.get('value',True)
                if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',key):raise PartyError('事实编号无效')
                if not isinstance(value,(str,int,float,bool)) or isinstance(value,float) and not math.isfinite(value) or len(str(value))>500:raise PartyError('事实值无效')
                if key in fields:raise PartyError('不能用剧情事实代替角色数值')
                working['world']['facts'][key]={'title':str(args.get('title') or key)[:100],'value':value};return
            if name=='set_flag':
                key=args.get('flag');key=key if key in working['world']['state'] else 'flag_'+str(key)
                if key not in working['world']['state'] or fields[key].type!='bool' or type(args.get('value')) is not bool:raise PartyError('标记未注册，已转待核对，不回滚其他合法变化')
                working['world']['state'][key]=args['value'];return
            if name=='enter_scene':
                scene=next((s for s in pack.scenes if s.id==args.get('scene_id')),None)
                if scene is None:raise PartyError('场景未注册')
                if working.get('scene_changed') and working['scene_changed']!=scene.id:raise PartyError('本轮共享转场存在冲突')
                for p in working['players'].values():
                    if unmet_conditions(scene.requires,{**working['world']['state'],**p['state']}):raise PartyError('有玩家尚未满足转场条件')
                working['world']['scene']=scene.id;working['scene_changed']=scene.id;return
            raise PartyError('该工具不能修改共享世界，必须指定具体角色')
        if actor not in working['players']:raise PartyError('目标角色不存在或不在本轮')
        identity=room['players'][actor]
        if identity['name'] not in op.evidence:raise PartyError('证据必须包含目标角色姓名，避免改错队友')
        player=working['players'][actor];current=player['state']
        if name=='transfer_item':
            target=args.get('to_actor_id');item=args.get('item_id');count=args.get('count')
            if target not in working['players'] or target==actor or room['players'][target]['name'] not in op.evidence:raise PartyError('转交对象或双方姓名证据无效')
            if type(count) is not int or count<1 or item not in {i.id for i in pack.items} or player['inventory'].get(item,0)<count:raise PartyError('转交物品或数量无效')
            player['inventory'][item]-=count;other=working['players'][target]['inventory'];other[item]=other.get(item,0)+count;return
        if name=='add_item':
            item=args.get('item_id');count=args.get('count',1)
            if item not in {i.id for i in pack.items} or type(count) is not int or count==0 or player['inventory'].get(item,0)+count<0:raise PartyError('物品或数量无效')
            if item in room['unique_items'] and count>0 and (count!=1 or any(p['inventory'].get(item,0) for p in working['players'].values())):raise PartyError('唯一物品已经被取得')
            player['inventory'][item]=player['inventory'].get(item,0)+count;return
        if name=='update_portrait':
            patch=portrait_changes(pack,current,args);current.update({k:v['after'] for k,v in patch.items()});return
        if name=='set_value':
            key=args.get('field');field=fields.get(key);value=args.get('value')
            if key not in current or field.group in ('appearance','sprite','flags','world') or field.type not in ('enum','string','bool'):raise PartyError('不能通过通用状态工具绕过资源或外观接口')
            if field.type=='enum' and value not in field.enum_values or field.type=='bool' and type(value) is not bool or field.type=='string' and (not isinstance(value,str) or len(value)>500):raise PartyError('状态值不合法')
            current[key]=value;return
        if name=='learn_catalog_skills':
            from .skill_catalog import learning_signal
            catalogue={c.ref:c for c in pack.skill_catalog};known={s['id'] for s in player['skills']};new=[]
            entries=args.get('skills')
            if not isinstance(entries,list) or len(entries)>50:raise PartyError('学习条目无效或过多')
            for item in entries:
                if not isinstance(item,dict):raise PartyError('学习条目格式无效')
                entry=catalogue.get(item.get('ref'));evidence=item.get('evidence','')
                if not entry or evidence not in narrative or identity['name'] not in evidence or not learning_signal(evidence) or not any(n in evidence for n in [entry.skill.name,*entry.aliases] if n):raise PartyError('学习证据或预设技能无效')
                if entry.skill.id not in known:new.append(entry);known.add(entry.skill.id)
            refs={c.ref for c in pack.skill_catalog if c.skill.id in known}
            if any(set(c.prerequisites)-refs for c in new):raise PartyError('学习缺少前置技能')
            player['skills'].extend(c.skill.model_dump(mode='json') for c in new);return
        if name not in ('damage','heal','add_stat','set_stat','update_clothing'):raise PartyError('工具不适用于个人状态')
        if name in ('damage','heal','add_stat','set_stat'):
            key=args.get('field',args.get('target',pack.state.resource_bindings.get('health','hp')))
            if key not in current:raise PartyError('资源字段不属于目标角色')
            if op.source=='skill_cost':
                if room['task']['paid'].get(actor,{}).get(key,0)>0:return
                raise PartyError('本轮没有该项已支付技能费用')
            for key_num in ('amount','value','delta'):
                if key_num in args and (isinstance(args[key_num],bool) or not isinstance(args[key_num],(int,float)) or not math.isfinite(args[key_num])):raise PartyError('资源变化必须是有限数字')
            if name in ('damage','heal'):args['target']=key
        executor=self._executor(pack,player)
        executor.set_skill_payments(room['task']['paid'].get(actor,{}))
        outcome=executor.execute(ToolCall(id='party',name=name,args=args),current,delta.setdefault(actor,{}),room['task']['round'],'party',narrative=narrative)
        if not outcome.result.ok:raise PartyError('工具校验失败')

    def _run(self,room_id,task_id):
        try:
            with self.lock:
                room=self._room(room_id);task=room['task']
                if task['id']!=task_id:return
                pack=self._pack(room);router=self.router_factory();frozen=copy.deepcopy(task);names={p['id']:p['name'] for p in room['players'].values()}
            players=[{'actor_id':i['actor_id'],'name':i['name'],**frozen['prepared'][i['actor_id']]} for i in frozen['inputs']]
            text=' '.join(i['text'] for i in frozen['inputs'])
            lore=[{'title':e.title,'content':e.content} for e in sorted(pack.worldbook,key=lambda e:-e.priority) if e.enabled and (e.always_on or any(k in text for k in e.keywords))][:12]
            if not frozen['narration_complete']:
                public_fields={f.id for f in pack.state.fields if f.display!='hidden' or f.group in ('appearance','sprite')}
                narrator_players=[{'actor_id':p['actor_id'],'name':p['name'],'state':{k:v for k,v in p['state'].items() if k in public_fields},'skills':[{'id':s['id'],'name':s['name']} for s in p['skills']]} for p in players]
                scene=next((s for s in [pack.opening,*pack.scenes] if s.id==room['world']['scene']),pack.opening)
                request={'phase':'party_narration','opening':frozen.get('kind')=='opening','allow_tools':False,'system_prompt':NARRATOR_PROMPT+'\n世界设定与文风：\n'+pack.prompts.get('pre','')+'\n'+pack.prompts.get('narrator','')+'\n最终协议：按姓名区分玩家，只输出共享正文和带actor_id的建议。',
                    'scene':{'id':scene.id,'title':scene.title,'text':scene.text},'players':narrator_players,'world':copy.deepcopy(room['world']),'inputs':frozen['inputs'],'worldbook':lore,'recent':[{'narrative':h['narrative']} for h in (([room['opening']] if room.get('opening') else [])+room['history'])[-4:]],'paid_skills':frozen['paid']}
                if frozen.get('kind')=='opening':request['system_prompt']+='\n本次是世界开场：根据设定和全体角色当前状态介绍共同起点，只建立场景，不替任何玩家采取行动。空的inputs不代表角色施放技能。'
                with self.lock:room['phase']='narrating';task['status']='narrating';task['text']='';self._save(room,'round.narrating',{'task_id':task_id})
                last=[0.0]
                def on_text(value):
                    with self.lock:
                        task['text']=str(value)[:40000]
                        if time.monotonic()-last[0]>.2:last[0]=time.monotonic();self._save(room,'narrative.delta',{'task_id':task_id,'text':task['text']})
                response=router.stream('narrator',request,on_text)
                if response.tool_calls:raise PartyError('叙事模型越权调用工具')
                result=response_data(response);narrative=str(result.get('narrative') or '').strip()
                if not narrative or len(narrative)>40000:raise PartyError('共享叙述为空或过长')
                options=[o for o in result.get('options',[]) if isinstance(o,dict) and o.get('actor_id') in names and isinstance(o.get('label'),str) and isinstance(o.get('action_text'),str)][:16]
                with self.lock:
                    task.update(text=narrative,narration_complete=True,options=options);self._usage(task,'narrator',response)
                    self._save(room,'narrative.completed',{'task_id':task_id,'text':narrative})
            else:narrative=frozen['text']
            with self.lock:room['phase']='settling';task['status']='settling';self._save(room,'round.settling',{'task_id':task_id})
            request={'phase':'party_settlement','allow_tools':True,'system_prompt':SETTLER_PROMPT,'narrative':narrative,'inputs':frozen['inputs'],
                'players':players,'world':copy.deepcopy(room['world']),'fields':[f.model_dump(mode='json') for f in pack.state.fields],
                'limits':pack.state.limits.model_dump(mode='json'),'resource_bindings':pack.state.resource_bindings,'paid_skills':frozen['paid'],
                'items':[{'id':i.id,'name':i.name} for i in pack.items],'unique_items':room['unique_items'],
                'wardrobe':wardrobe_snapshot(pack.wardrobe,players[0]['state'],narrative) if pack.wardrobe else {},'portrait':portrait_snapshot(pack,players[0]['state'],narrative),
                'skill_catalog':[{'ref':e.ref,'name':e.skill.name,'aliases':e.aliases,'prerequisites':e.prerequisites} for e in pack.skill_catalog],
                'scenes':[{'id':s.id,'title':s.title} for s in pack.scenes],'rules':pack.prompts.get('settler','')[:6000]}
            for attempt in range(2):
                response=router.complete('settler',request)
                with self.lock:self._usage(task,'settler',response)
                try:
                    if response.tool_calls:
                        if len(response.tool_calls)!=1 or response.tool_calls[0].name!='settle_party_round':raise PartyError('只允许一次settle_party_round')
                        proposal=PartyProposal.model_validate(response.tool_calls[0].args)
                    else:proposal=PartyProposal.model_validate(response_data(response))
                    break
                except (ValueError,TypeError) as exc:
                    if attempt:raise PartyError('多人结算格式仍不正确，正文已保留，请重试结算') from None
                    request['validation_feedback']=str(exc)[:500]
            with self.lock:
                working={'world':copy.deepcopy(room['world']),'players':copy.deepcopy(task['prepared'])};delta={};seen=set();pending=[]
                for op in proposal.operations:
                    fingerprint=digest(op.model_dump(mode='json'))
                    if fingerprint in seen:continue
                    seen.add(fingerprint);trial=copy.deepcopy(working);trial_delta=copy.deepcopy(delta)
                    try:self._apply(room,trial,op,narrative,trial_delta);working=trial;delta=trial_delta
                    except Exception as exc:pending.append({'id':uid('pending'),'round':task['round'],'reason':str(exc)[:400],'operation':op.model_dump(mode='json')})
                pending.extend({'id':uid('pending'),'round':task['round'],'reason':note[:400],'operation':None} for note in proposal.uncertain)
                # Persist a complete candidate before replacing the authority in memory.
                candidate=copy.deepcopy(room);candidate_task=candidate['task']
                room=candidate;task=candidate_task
                room['world']=working['world']
                for actor,data in working['players'].items():room['players'][actor].update(data)
                room['round']=task['round'];room['phase']='collecting';room['round_token']=uid('round');room['pending']=(room['pending']+pending)[-100:]
                if task.get('kind')=='opening':
                    room['opening']={'task_id':task_id,'narrative':narrative,'options':task['options']};room['opening_generated']=True
                else:room['history'].append({'round':room['round'],'task_id':task_id,'inputs':task['inputs'],'narrative':narrative,'options':task['options']})
                room['history']=room['history'][-100:]
                for p in room['players'].values():p.update(intent=None,ready=False,intent_revision=p['intent_revision']+1)
                task.update(status='committed',error='');before=task.pop('before');task.pop('prepared',None)
                self._save(room,'state.committed',{'task_id':task_id,'pending_count':len(pending)},before=before if task.get('kind')!='opening' else None)
                self.rooms[room_id]=room
        except Exception:
            with self.lock:
                room=self._room(room_id);task=room['task']
                if task and task['id']==task_id:
                    room['phase']='failed';task['status']='failed';task['error']='本阶段未提交状态。请检查房主模型设置后重试；已完成的正文不会重新生成。'
                    self._save(room,'round.failed',{'task_id':task_id})

    def _usage(self,task,role,response):
        task['usage'].append({'role':role,'model':response.model,'usage':response.usage,'cost_usd':response.cost_usd})

    def retry(self,room_id,token,request_id):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._host(room,p);body=['retry',room['task']['id'] if room['task'] else None];key,old=self._seen(room,p,request_id,body)
            if not old:
                if room['phase']!='failed':raise PartyError('当前没有需要重试的阶段',409)
                room['phase']='frozen';room['task']['status']='frozen';room['task']['error']='';self._receipt(room,key,body)
                self._save(room,'round.retrying',{'task_id':room['task']['id']});self.pool.submit(self._run,room_id,room['task']['id'])
            return self.view(room_id,token)

    def leave(self,room_id,token):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._collecting(room)
            p['active']=False;p['ready']=False
            if p['id']==room['owner']:room['phase']='closed'
            self._save(room,'member.left',{'player_id':p['id'],'closed':room['phase']=='closed'})
            return {'ok':True}

    def cancel_failed(self,room_id,token):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._host(room,p)
            if room['phase']!='failed':raise PartyError('只能放弃尚未提交的失败回合',409)
            room['task']=None;room['phase']='collecting';room['round_token']=uid('round')
            for member in room['players'].values():member.update(ready=False,intent=None,intent_revision=member['intent_revision']+1)
            self._save(room,'round.cancelled',{});return self.view(room_id,token)

    def propose_undo(self,room_id,token):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._collecting(room)
            if not room['round']:raise PartyError('没有可回退的共同回合')
            room['undo']={'id':uid('undo'),'round':room['round'],'votes':{p['id']:True},'eligible':[p['id'] for p in room['players'].values() if p['active']]};room['phase']='undo_pending'
            self._save(room,'undo.proposed',{'player_id':p['id']});return self.view(room_id,token)

    def vote_undo(self,room_id,token,proposal_id,agree):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);proposal=room['undo']
            if room['phase']!='undo_pending' or not proposal or proposal['id']!=proposal_id or p['id'] not in proposal['eligible']:raise PartyError('回退提议已失效',409)
            proposal['votes'][p['id']]=bool(agree)
            if not agree:room['phase']='collecting';room['undo']=None;self._save(room,'undo.rejected',{})
            elif all(proposal['votes'].get(actor) for actor in proposal['eligible']):
                with self._db() as db:row=db.execute('SELECT data FROM snapshots WHERE room=? AND round=?',(room_id,room['round'])).fetchone()
                if not row:raise PartyError('回退快照缺失',409)
                before=json.loads(row[0]);room['world']=before['world']
                for actor,data in before['players'].items():room['players'][actor].update(data)
                room['round']-=1;room['history']=[h for h in room['history'] if h['round']<=room['round']];room['task']=None;room['undo']=None
                room['phase']='collecting';room['epoch']=uid('epoch');room['round_token']=uid('round')
                for member in room['players'].values():member.update(intent=None,ready=False,intent_revision=member['intent_revision']+1)
                self._save(room,'room.rewound',{})
            else:self._save(room,'undo.voted',{'player_id':p['id']})
            return self.view(room_id,token)

    def dismiss(self,room_id,token,pending_id):
        with self.lock:
            room=self._room(room_id);p=self._auth(room,token);self._host(room,p);self._collecting(room)
            room['pending']=[item for item in room['pending'] if item['id']!=pending_id];self._save(room,'pending.dismissed',{})
            return self.view(room_id,token)

    def events(self,room_id,token,after):
        with self.lock:
            room=self._room(room_id);self._auth(room,token)
            with self._db() as db:rows=db.execute('SELECT seq,kind,data FROM events WHERE room=? AND seq>? ORDER BY seq LIMIT 200',(room_id,after)).fetchall()
            return [{'seq':r[0],'kind':r[1],'data':json.loads(r[2])} for r in rows]

    def asset(self,room_id,token,relative):
        with self.lock:
            room=self._room(room_id);self._auth(room,token)
            if '\\' in relative or any(p in ('..','.') for p in relative.split('/')) or not relative.startswith('ui/') or Path(relative).suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.svg'):raise PartyError('资源路径无效',403)
            for base in [Path(room['asset_root']),Path(room['fallback_root'])]:
                target=(base/relative).resolve()
                if target.is_relative_to(base.resolve()) and target.is_file():return target
            raise PartyError('房间素材缺失',404)

    def sheet(self,room_id,token):
        with self.lock:
            room=self._room(room_id);self._auth(room,token);pack=self._pack(room)
            return {'sheet':pack.sprites.model_dump(mode='json') if pack.sprites else None,'asset_revision':room['pack_key']}

    def close(self):self.closed=True;self.pool.shutdown(wait=False,cancel_futures=True)
