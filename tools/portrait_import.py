"""Add ordinary portrait controls, accessories and reviewed decorations.

This importer deliberately stays outside sex/bodywriting/genitals/back assets.
It augments an existing aligned sheet; it does not enable adult rendering.
"""
from __future__ import annotations
import argparse,hashlib,json,re,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pngio
from dol_import import _aligned, _isolate_character, _primary_image

POSES={'stand':'站立','hold':'持物','guard':'护身','talk':'交谈','walk':'行走表现','run':'奔跑表现','jump':'跳跃表现','attack':'攻击表现','cast':'施法表现','hurt':'受击表现'}
EXPRESSIONS={'default':'平静','aloof':'冷淡','catty':'俏皮','foxy':'从容','gloomy':'低落','makeup':'淡妆','red':'认真','sweet':'温柔',
 'smile':'微笑','laughing':'开怀','sad':'悲伤','angry':'生气','surprised':'惊讶','scared':'害怕','shy':'害羞','tired':'疲倦'}
SLOTS={'headwear':('head','帽饰',65),'facewear':('face','面饰',67),'neckwear':('neck','颈饰',58),
 'handwear':('hands','手饰',62),'legwear':('legs','袜饰',43),'footwear':('feet','鞋子',46),
 'earrings':('earrings','耳饰',64),'fingerwear':('rings','戒指',63),'handheld':('handheld','持物',70)}
BLOCK=re.compile(r'fetish|leash|lewd|gag|muzzle|chastity|strapon|butt|plug|semen|aphrodisiac|breast|parasite|shackle|freeuse|harness|stripper|succubus|panty|panties|ropes|ballchain|collar|pimp',re.I)
LABELS={'witch':'巫师帽','witchstarry':'星纹巫师帽','witchsage':'贤者帽','bow':'蝴蝶结','beanie':'针织帽','cap':'鸭舌帽','glasses':'眼镜','round':'圆框眼镜','monocle':'单片镜','scarf':'围巾','tie':'领带','gold necklace':'金项链','workgloves':'工作手套','fingerlessgloves':'露指手套','trainers':'运动鞋','schoolshoes':'皮鞋','anklesocks':'短袜','tights':'连裤袜','umbrella':'雨伞','witch broom':'扫帚','book':'书本','copper compass':'铜罗盘'}

def condition(field,value,op='=='):return {'field':field,'op':op,'value':value}
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')

def upgrade(pack:Path,dol:Path):
    img=dol/'img';path=pack/'ui/sprites.json';sheet=json.loads(path.read_text(encoding='utf-8'))
    state=json.loads((pack/'state.json').read_text(encoding='utf-8'));fields={f['id']:f for f in state['fields']}
    wardrobe=json.loads((pack/'wardrobe.json').read_text(encoding='utf-8'))
    controls={};labels={};imported=[]
    layers=[layer for layer in sheet['layers'] if not layer['id'].startswith('portrait_')]
    backup=pack.parent.parent/'build/portrait-template-backups'/pack.name/'sprites.json'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():shutil.copy2(path,backup)
    def field(key,label,options=None,default=None,kind='enum',low=None,high=None):
        new={'id':key,'label':label,'type':kind,'default':default,'display':'hidden','group':'appearance','llm_visible':False}
        if options is not None:new['enum_values']=list(options)
        if low is not None:new['min']=low
        if high is not None:new['max']=high
        if key in fields:
            if options is not None:fields[key]['enum_values']=list(dict.fromkeys([*fields[key].get('enum_values',[]),*options]))
        else:state['fields'].append(new);fields[key]=new
    def control(key,label,options,default):
        field(key,label,options,default);controls[key]=options
    def add(id,src,z,when=None,**more):
        layer={'id':'portrait_'+id,'src':src,'z':z,**more}
        if when:layer['when']=when
        layers.append(layer)
    def copy(source,relative,character=True,closed=False):
        destination=pack/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,destination)
        if closed:
            w,h,pixels=pngio.read_png_rgba(destination)
            scale=256//h if h in (128,256) else 1
            stride=256//scale
            if w>=stride*2:
                pixels=b''.join(pixels[(y*w+stride)*4:(y*w+stride*2)*4] for y in range(h))
                pngio.encode_png_rgba(destination,stride,h,pixels)
        if character:_isolate_character(destination)
        imported.append(relative)
        return relative

    control('pose','动作',POSES,'stand')
    control('left_arm','左臂',{'auto':'随动作','idle':'自然放下','cover':'护身'},'auto')
    control('right_arm','右臂',{'auto':'随动作','idle':'自然放下','cover':'护身','hold':'持物'},'auto')
    control('eye_state','眼睑',{'auto':'随表情','open':'睁眼','half':'半闭','closed':'闭眼'},'auto')
    control('gaze','视线',{'forward':'正前方','left':'左看','right':'右看'},'forward')
    control('mouth_shape','嘴型',{'auto':'随表情/交谈','neutral':'自然','smile':'微笑','frown':'皱嘴','cry':'哭泣','chew':'张口'},'auto')
    field('tears','眼泪',default=0,kind='int',low=0,high=4);controls['tears']={}
    field('freckles','雀斑',default=False,kind='bool');controls['freckles']={}
    controls['blush']={}

    # Reuse ordinary clean face parts; emotion presets never select explicit art.
    profiles={'smile':('mid','smile',False),'laughing':('top','smile',True),'sad':('low','frown',True),
      'angry':('low','frown',False),'surprised':('top','cry',False),'scared':('top','frown',False),
      'shy':('mid','smile',True),'tired':('low','neutral',True)}
    root=img/'face/default'
    for emotion,(brow,mouth,half) in profiles.items():
        source=next((p for p in layers if p['id']=='face_default_base'),None)
        for part in ['base','ears','sclera','eyelids','lashes','brow','mouth']:
            name=f'brow-{brow}' if part=='brow' else f'mouth-{mouth}' if part=='mouth' else part+('-half-closed' if half and part in ['eyelids','lashes'] else '')
            dest=copy(root/(name+'.png'),f'ui/sprites/face/{emotion}/{part}.png')
            layer={'id':f'face_{emotion}_{part}','src':dest,'z':{'base':31,'ears':32,'sclera':34,'eyelids':38,'lashes':39,'brow':41,'mouth':43}[part],'when':[condition('expression',emotion)]}
            if part=='brow':layer['tint_field']='hair_color'
            # Use portrait_ prefix so subsequent runs replace rather than duplicate.
            layer['id']='portrait_'+layer['id'];layers.append(layer)
        iris=root/'foxy'/('iris-half-closed.png' if half else 'iris.png')
        copy(iris if iris.exists() else root/'foxy/iris.png',f'ui/sprites/face/{emotion}/iris.png')
        for level in range(1,6):
            dest=copy(root/f'blush-{level}.png',f'ui/sprites/face/{emotion}/blush-{level}.png')
            add(f'blush_{emotion}_{level}',dest,37,[condition('expression',emotion),condition('blush',level)])
    expression_options={value:EXPRESSIONS.get(value,'预设 '+value.replace('modded','')) for value in [*fields['expression']['enum_values'],*profiles]}
    control('expression','表情',expression_options,'default')
    for layer in layers:
        name=layer['id'].removeprefix('portrait_')
        if name.startswith('face_') and name.rsplit('_',1)[-1] in ['sclera','eyelids','lashes']:
            layer['when']=[c for c in layer.get('when',[]) if c['field']!='eye_state']+[condition('eye_state','auto')]
        if name.startswith('face_') and name.endswith('_mouth'):
            layer['when']=[c for c in layer.get('when',[]) if c['field']!='portrait_mouth']+[condition('portrait_mouth','auto')]
        if name.startswith('eyes_'):
            layer['when']=[c for c in layer.get('when',[]) if c['field'] not in ['eye_state','gaze']]+[condition('eye_state','auto'),condition('gaze','forward')]
    for eye_state in ['open','half']:
        suffix='-half-closed' if eye_state=='half' else ''
        for part,z in [('sclera',34),('eyelids',38),('lashes',39)]:
            src=root/(part+suffix+'.png') if part!='sclera' else root/'sclera.png'
            relative=copy(src,f'ui/sprites/portrait/face/{part}-{eye_state}.png')
            add(f'{part}_{eye_state}',relative,z,[condition('eye_state',eye_state)])
    closed=copy(root/'lashes.png','ui/sprites/portrait/face/closed.png',closed=True)
    add('eyes_closed',closed,39,[condition('eye_state','closed')])
    colours={'hazel':'#877334','blue':'#507eaa','brown':'#705035','green':'#52805a','grey':'#7d858b'}
    for gaze in ['forward','left','right']:
        for eye_state in ['open','half','auto']:
            if gaze=='forward' and eye_state=='auto':continue
            suffix='-half-closed' if eye_state=='half' else ''
            name='iris'+suffix+('-'+gaze if gaze!='forward' else '')+'.png'
            src=root/'foxy'/name
            if not src.exists():src=root/name
            if not src.exists():src=root/'foxy/iris.png'
            relative=copy(src,f'ui/sprites/portrait/face/iris-{eye_state}-{gaze}.png')
            for eye,tint in colours.items():
                mask='ui/sprites/face/{expression}/sclera.png' if eye_state=='auto' else f'ui/sprites/portrait/face/sclera-{eye_state}.png'
                add(f'iris_{eye_state}_{gaze}_{eye}',relative,36,[condition('eye_state',eye_state),condition('gaze',gaze),condition('eye_color',eye)],tint=tint,mask=mask)
    for shape in ['neutral','smile','frown','cry','chew']:
        relative=copy(root/f'mouth-{shape}.png',f'ui/sprites/portrait/face/mouth-{shape}.png')
        add('mouth_'+shape,relative,43,[condition('portrait_mouth',shape)])
    for level in range(1,5):
        relative=copy(root/f'tears-{level}.png',f'ui/sprites/portrait/face/tears-{level}.png')
        add('tears_'+str(level),relative,44,[condition('tears',level)])
    relative=copy(root/'freckles.png','ui/sprites/portrait/face/freckles.png')
    add('freckles',relative,40,[condition('freckles',True)])

    # Body and sleeves switch together; idle art must not remain underneath.
    for layer in layers:
        name=layer['id']
        if name.startswith('arm_left_') or name.startswith('arm_right_'):
            side=name.split('_')[1];layer['when']=[c for c in layer['when'] if c['field']!=f'portrait_{side}_arm']+[condition(f'portrait_{side}_arm','idle')]
        if name.startswith('upper_piece_') and name.endswith(('_left_None','_right_None')):
            side='left' if name.endswith('_left_None') else 'right';layer['when']=[c for c in layer['when'] if c['field']!=f'portrait_{side}_arm']+[condition(f'portrait_{side}_arm','idle')]
    for body in fields['body_type']['enum_values']:
        for side,modes in [('left',['cover']),('right',['cover','hold'])]:
            for mode in modes:
                candidates=[img/'body'/f'{side}arm{mode}-{body}.png',img/'body'/f'{side}-arm-{mode}.png']
                src=next((p for p in candidates if p.exists()),None)
                if src is None:continue
                relative=copy(src,f'ui/sprites/portrait/arms/{side}-{mode}-{body}.png')
                add(f'arm_{side}_{mode}_{body}',relative,53,[condition('body_type',body),condition(f'portrait_{side}_arm',mode)])
    for garment in fields['upper']['enum_values']:
        directory=img/'clothes/upper'/garment
        for side,modes in [('left',['cover']),('right',['cover','hold'])]:
            for mode in modes:
                src=directory/f'{side}-{mode}.png'
                if not src.exists() or not _aligned(src):continue
                relative=copy(src,f'ui/sprites/portrait/sleeves/{garment}/{side}-{mode}.png')
                add(f'sleeve_{side}_{mode}_{garment}',relative,54,[condition('upper',garment),condition(f'portrait_{side}_arm',mode)],tint_field='outfit_color',wear_field='upper_condition')

    counts={}
    for key,(directory,label,z) in SLOTS.items():
        options={'none':'无'}
        for folder in sorted((img/'clothes'/directory).iterdir()):
            if not folder.is_dir() or BLOCK.search(folder.name):continue
            if directory=='face' and folder.name in ['belly','blindfold']:continue
            if directory=='hands' and folder.name in ['belted','cow','gold','metal','wristcuffs']:continue
            if directory=='legs' and any(s in folder.name for s in ['garter','sheer','fishnet','leather','belted','cow']):continue
            if directory=='handheld' and folder.name in ['baby bottle','milk bottle','pill bottle']:continue
            primary=_primary_image(folder)
            variants=[]
            if directory in ['hands','rings']:
                for side,modes in [('left',['idle','cover']),('right',['idle','cover','hold'])]:
                    for mode in modes:
                        candidate=folder/f'{side}-{mode}.png'
                        if not candidate.exists():candidate=folder/f'{side}.png'
                        if candidate.exists() and _aligned(candidate):variants.append((candidate,side,mode))
            if not variants and (primary is None or not _aligned(primary)):continue
            options[folder.name]=LABELS.get(folder.name,folder.name)
            when=[condition(key,folder.name)]
            if variants:
                for src,side,mode in variants:
                    relative=copy(src,f'ui/sprites/portrait/accessories/{key}/{folder.name}/{side}-{mode}.png')
                    add(f'{key}_{folder.name}_{side}_{mode}',relative,z,when+[condition(f'portrait_{side}_arm',mode)],tint_field=key+'_color',wear_field=key+'_condition')
            else:
                relative=copy(primary,f'ui/sprites/portrait/accessories/{key}/{folder.name}/full.png')
                add(f'{key}_{folder.name}',relative,z,when,tint_field=key+'_color',wear_field=key+'_condition')
                for part,pz in [('back',6),('acc',z+1),('buckle',z+2)]:
                    src=folder/f'{part}.png'
                    if src.exists() and _aligned(src):
                        relative=copy(src,f'ui/sprites/portrait/accessories/{key}/{folder.name}/{part}.png')
                        add(f'{key}_{folder.name}_{part}',relative,pz,when,wear_field=key+'_condition')
        if len(options)==1:continue
        field(key,label,options,'none');field(key+'_color',label+'颜色',default='#ffffff',kind='string')
        field(key+'_condition',label+'状态',{'intact':'完好','scuffed':'磨损','damaged':'破损','ruined':'严重破损'},'intact')
        wardrobe['slots'][key]={'field':key,'condition_field':key+'_condition','color_field':key+'_color','items':options}
        labels[key]=options;counts[key]=len(options)-1

    # All these numbered sheets were visually reviewed. Skip empty slots and
    # legacy UI overlays whose labels/content do not belong in an all-ages RPG.
    for key,groups,space,z in [
      ('decoration_background',['background','background1','background2'],'background',-100),
      ('decoration_foreground',['foreground','foreground1','foreground2'],'foreground',100)]:
        options={'none':'无'};seen={}
        for group in groups:
            for src in sorted((img/'decorations'/group).glob('*.png'),key=lambda p:(not p.stem.isdigit(),int(p.stem) if p.stem.isdigit() else 0)):
                if not src.stem.isdigit():continue
                number=int(src.stem)
                if group.startswith('foreground') and number in {14,16,17,19,35,43,44}:continue
                if group=='background1' and number==217:continue
                w,h,pixels=pngio.read_png_rgba(src)
                if (w,h)!=(512,256) or not any(pixels[3::4]):continue
                digest=hashlib.sha256(pixels).hexdigest()
                if digest in seen:continue
                value=f'{group}-{number}';seen[digest]=value
                options[value]=('背景' if space=='background' else '前景')+f' · {group}/{number}'
                relative=f'ui/sprites/portrait/decorations/{group}/{src.name}'
                dest=pack/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                # Fit each decorative frame around the exact existing portrait crop.
                out=bytearray(512*256*4)
                for frame in range(2):
                    for y in range(190):
                        sy=y*256//190
                        for x in range(212):
                            sx=frame*256+x*256//212
                            at=(y*512+frame*256+12+x)*4
                            source=(sy*w+sx)*4
                            out[at:at+4]=pixels[source:source+4]
                pngio.encode_png_rgba(dest,512,256,out);imported.append(relative)
                add(value,relative,z,[condition(key,value)],space=space)
        control(key,'背景装饰' if space=='background' else '前景装饰',options,'none')
        counts[key]=len(options)-1
    (pack/'ui/sprites/portrait/decorations/CREDITS.txt').write_text((img/'decorations/readme.txt').read_text(encoding='utf-8',errors='replace'),encoding='utf-8')

    sheet.update({'layers':layers,'controls':controls,'labels':labels,'revision':1,
      'legacy_hashes':[hashlib.sha256(backup.read_bytes()).hexdigest()],
      'motions':{'stand':'none','hold':'sway','guard':'none','talk':'sway','walk':'walk','run':'run','jump':'jump','attack':'attack','cast':'cast','hurt':'hurt'},'rules':[]})
    write(path,sheet);write(pack/'state.json',state);write(pack/'wardrobe.json',wardrobe)
    report={'schema_version':1,'expressions':len(expression_options),'actions':POSES,'counts':counts,'imported_files':len(set(imported)),
      'motions_are_procedural':True,'explicit_assets_imported':False,'decorative_sources':'DoL+ DecoMod; original individual credits retained in decorations/CREDITS.txt'}
    write(pack/'ui/portrait-catalog.json',report)
    from portrait_labels import apply
    apply(pack)
    from portrait_parts import apply as complete_parts
    complete_parts(pack,dol)
    print(json.dumps(report,ensure_ascii=True),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dol',type=Path,required=True);parser.add_argument('--pack',type=Path,required=True);args=parser.parse_args()
    upgrade(args.pack,args.dol)
