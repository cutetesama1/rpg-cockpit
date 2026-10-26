"""Complete split handheld layers and fit opaque scenery to the portrait stage."""
import json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pngio
from dol_import import _aligned,_isolate_character

def apply(pack:Path,dol:Path):
 p=pack/'ui/sprites.json';sheet=json.loads(p.read_text(encoding='utf-8'))
 wardrobe=json.loads((pack/'wardrobe.json').read_text(encoding='utf-8'))
 layers=[l for l in sheet['layers'] if not l['id'].startswith(('portrait_handheld_','portrait_accessory_part_','portrait_position_','portrait_earring_graphic_'))]
 preferences={};supported={}
 def cond(field,value):return {'field':field,'op':'==','value':value}
 def copy(src,relative):
  dest=pack/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest);_isolate_character(dest)
  return relative
 for key,folder_name in [('handheld','handheld'),('handwear','hands'),('fingerwear','rings')]:
  for name in wardrobe['slots'][key]['items']:
   if name=='none':continue
   directory=dol/'img/clothes'/folder_name/name
   if key=='handheld':
    variants=[]
    for mode in ['cover','hold']:
     src=directory/f'right-{mode}.png'
     if src.exists() and _aligned(src):variants.append((src,mode))
     else:
      for tone in ['light','dark']:
       candidate=directory/f'right-{mode}-{tone}.png'
       if candidate.exists() and _aligned(candidate):variants.append((candidate,mode))
    if not variants:
     src=directory/'right.png'
     if src.exists() and _aligned(src):
      iw,ih,rgba=pngio.read_png_rgba(src)
      top=next((y*(256//ih) for y in range(ih) if any(rgba[y*iw*4+3:(y*iw+min(iw,256))*4:4])),0)
      variants=[(src,'idle' if top>115 else 'hold')]
     else:
      src=directory/'full.png'
      if src.exists() and _aligned(src):variants=[(src,'hold')]
    supported[name]=[mode for _,mode in variants if mode]
    preferences[name]='hold' if 'hold' in supported[name] else 'idle'
    for src,mode in variants:
     part=src.stem if src.stem.endswith(('-light','-dark')) else 'right-'+mode if mode else 'full'
     relative=copy(src,f'ui/sprites/portrait/accessories/{key}/{name}/{part}.png')
     conditions=[cond(key,name)]+([cond('portrait_right_arm',mode)] if mode else [])
     if src.stem.endswith(('-light','-dark')):conditions.append(cond('accessory_tone',src.stem.rsplit('-',1)[1]))
     layers.append({'id':f'portrait_handheld_{name}_{part}','src':relative,'z':70,'when':conditions,'tint_field':key+'_color','wear_field':key+'_condition'})
    for part,z in [('back',7),('back-acc',8),('acc',71)]:
     src=directory/(part+'.png')
     if src.exists() and _aligned(src):
      relative=copy(src,f'ui/sprites/portrait/accessories/{key}/{name}/{part}.png')
      layers.append({'id':f'portrait_handheld_{name}_{part}','src':relative,'z':z,'when':[cond(key,name)],'wear_field':key+'_condition'})
   for side,modes in [('left',['idle','cover']),('right',['idle','cover','hold'])]:
    for mode in modes:
     src=directory/f'{side}-{mode}-acc.png'
     if not src.exists() or not _aligned(src):continue
     relative=copy(src,f'ui/sprites/portrait/accessories/{key}/{name}/{side}-{mode}-acc.png')
     layers.append({'id':f'portrait_accessory_part_{key}_{name}_{side}_{mode}','src':relative,'z':71 if key=='handheld' else 64,
       'when':[cond(key,name),cond('portrait_'+side+'_arm',mode)],'wear_field':key+'_condition'})
 state_path=pack/'state.json';state=json.loads(state_path.read_text(encoding='utf-8'));fields={f['id']:f for f in state['fields']}
 def add_control(key,label,options,default):
  sheet['controls'][key]=options
  if key not in fields:state['fields'].append({'id':key,'label':label,'type':'enum','enum_values':list(options),'default':default,'display':'hidden','group':'appearance','llm_visible':False})
 add_control('accessory_tone','饰品明暗',{'light':'浅色','dark':'深色'},'light')
 add_control('hairpin_position','发夹位置',{'high':'高位','low':'低位'},'high')
 for name in ['apple hairpin','green apple hairpin']:
  layers=[l for l in layers if not any(c.get('field')=='headwear' and c.get('value')==name for c in l.get('when',[]))]
  for position in ['high','low']:
   src=dol/'img/clothes/head'/name/(position+'.png')
   if src.exists():
    relative=copy(src,f'ui/sprites/portrait/accessories/headwear/{name}/{position}.png')
    layers.append({'id':f'portrait_position_{name}_{position}','src':relative,'z':65,'when':[cond('headwear',name),cond('hairpin_position',position)],'tint_field':'headwear_color','wear_field':'headwear_condition'})
 directory=dol/'img/clothes/earrings/graphic'
 graphics={src.stem.removeprefix('full-'):src for src in directory.glob('full-*.png') if src.stem not in ('full-cock',)}
 add_control('earring_graphic','图案耳环样式',{key:key for key in graphics},'heart')
 layers=[l for l in layers if not any(c.get('field')=='earrings' and c.get('value')=='graphic' for c in l.get('when',[]))]
 for graphic,src in graphics.items():
  relative=copy(src,f'ui/sprites/portrait/accessories/earrings/graphic/full-{graphic}.png')
  layers.append({'id':f'portrait_earring_graphic_{graphic}','src':relative,'z':64,'when':[cond('earrings','graphic'),cond('earring_graphic',graphic)],'wear_field':'earrings_condition'})
 state_path.write_text(json.dumps(state,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
 sheet['arm_preferences']=preferences;sheet['handheld_modes']=supported
 for layer in layers:
  if layer.get('space')!='background':continue
  dest=pack/layer['src'];parts=Path(layer['src']).parts;src=dol/'img/decorations'/parts[-2]/parts[-1]
  w,h,pixels=pngio.read_png_rgba(src)
  coords=[(x,y) for y in range(256) for x in range(256) if pixels[(y*w+x)*4+3]]
  if not coords:continue
  x0=min(x for x,y in coords);x1=max(x for x,y in coords)+1;y0=min(y for x,y in coords);y1=max(y for x,y in coords)+1
  bw,bh=x1-x0,y1-y0
  if bw<64 or bh<64 or len(coords)/(bw*bh)<.90:continue
  scale=max(212/bw,190/bh);sample_w=212/scale;sample_h=190/scale
  ox=x0+(bw-sample_w)/2;oy=y0+(bh-sample_h)/2
  out=bytearray(512*256*4)
  for frame in range(2):
   for y in range(190):
    sy=min(y1-1,int(oy+y/scale))
    for x in range(212):
     sx=frame*256+min(x1-1,int(ox+x/scale));source=(sy*w+sx)*4;at=(y*512+frame*256+12+x)*4
     out[at:at+4]=pixels[source:source+4]
  pngio.encode_png_rgba(dest,512,256,out)
 sheet['layers']=layers
 p.write_text(json.dumps(sheet,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
 print('Completed held-item layers and full-stage scenery.',flush=True)

if __name__=='__main__':
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--pack',type=Path,required=True);a.add_argument('--dol',type=Path,required=True);args=a.parse_args();apply(args.pack,args.dol)
