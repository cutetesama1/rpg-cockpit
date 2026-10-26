"""Readable catalog labels for the reviewed ordinary accessories and decorations."""
import json,re
from pathlib import Path

SCENES='''木屋书房|蓝色符文室|星空法阵|山中古宅|奇幻藏宝室|薄雾庭院|幽暗森林|雪夜庭院|彩色小铺|烛光木屋|旧式街区|山间小亭|花园拱门|粉色卧室|阳光海滩|海边黄昏|彩色儿童房|玩具城堡|春日喷泉|雨中公路|秋日公园|秋日湖畔|落日风车|乡间小路|梦幻花丘|欧式花园|秋日农舍|秋日栅栏|温暖榻榻米|晴日海岸|棕榈树海滩|热带沙滩|河岸小径|神社参道|古老庙门|彩虹云海|金色云海|童话云端城|星月书页|月夜花园|童话花园|竹林|水墨荒山|冬日村庄|彩色公园|绿野小道|枯树废土|田间小路|春日村庄|浅溪草地|乡间花屋|雪原远山|草地风车|晴空草原|森林大树|林中阳光|花田池畔|粉色花田|星夜水面|雪中小镇|荒漠城墙|紫色暗林|城堡废墟|山顶宅邸|城堡大道|园林小桥|山野草原|石室牢门|旧式教室|战后残垣|林中木屋|庭院石碑|地下走廊|花园石门|室内泳池|废弃花园|木制图书馆|雨夜街巷|明亮客房|喷泉花园|教堂大厅|密林山谷|林中小路|书店柜台|森林遗迹|静谧圣堂|暗色卧室|更衣储物柜|夜晚露台|庄园红毯|林中茅屋|暖色走廊|都市书房|幽暗小屋|圣堂长廊|月下阳台|街边小店|阳光废室|霓虹走廊|石砖大厅|现代卧室|红色会客厅|壁炉客厅|复古会客室|蓝绿客房|暗色旧屋|阴暗洞窟|四柱木床|月夜庭院|秋日房间|紫藤步道|池畔草地|蓝色宫殿|古旧木房|阳光林荫道|石门小径|剧场红帘|城市天桥|金色走廊|遗迹通道|石牢|荒废地窖|幽暗圣殿|彩窗大厅|古老石殿|深山遗迹|欧式大宅|灰色祭坛|木屋楼梯|壁炉书房|紫色茶室|冰雪荒原|山间教堂|复古卧室|仓库纸箱|紫色卧室|华丽客房|月夜庄园|红光长廊|奇幻杂货铺|木制柜台|旋转楼梯|春日河谷|远山草原|古堡楼梯|剧场舞台|现代淋浴间|水泥楼梯|石砖地道|绿窗石室|烛火走廊|复古酒馆|夜色公馆|白墙宅邸|雪夜小屋|粉色花林|幽暗遗迹|废墟街巷|夕阳旧街|夜晚花园|现代庭院|城市客厅|白花公园|地下石窟|紫雾荒原|绿色遗迹|地下楼梯|红色荒野|传统庭院|春日园林|古典长廊|石砖工作间|奇幻室内花园|明亮公寓|钟表工坊|深蓝夜空|红色荒漠|蓝夜森林|石砌小径|青翠山谷|星光庭院|冰蓝宫殿|春日广场|海岸观景窗|霓虹街区|雪中枯树|紫色天空|蓝月海滩|漫画拼贴墙|月夜窗台|粉色相框|黑白相框|甜点背景|暖色走廊|粉色格纹|秋日庭院|月光卧室|紫色夜窗|粉色街景|木屋壁灯|紫色房间|粉色灯光|春日小巷|樱花庭院|樱花步道|落日观景台|蓝光花园|荧光森林|灯光温室|粉色花纹|古典书屋|温暖书房|魔法符文室|星光法阵|古宅院门|奇幻藏宝屋|复古广告|红花暗室|雾中森林'''.split('|')
GEMS={'black-diamond':'黑钻','amethyst':'紫水晶','aquamarine':'海蓝宝','diamond':'钻石','emerald':'绿宝石','ruby':'红宝石','sapphire':'蓝宝石','spinel':'尖晶石','tanzanite':'坦桑石','topaz':'黄玉','morganite':'摩根石','opal':'欧泊','gold':'黄金','silver':'白银','copper':'铜','coral':'珊瑚'}
FG={1:'漂浮蝙蝠',2:'蓝色边框',3:'缎带',4:'金色边框',5:'紫色蝴蝶',6:'蓝色蝴蝶',7:'银色相框',8:'粉色花框',9:'红色蝴蝶结框',10:'白色手机框',11:'金色蝴蝶',12:'枝条边框',13:'透明泡泡',15:'白色相框',18:'羽毛',20:'玫红边框',21:'白色相片框',22:'花叶边框',23:'红色光点',24:'宝石挂坠',25:'深红边框',26:'星月吊饰',27:'橄榄绿边框',28:'蓝色波纹框',29:'紫色飞蝶',30:'小鸡吊饰',31:'夜色飞鸟',32:'铅笔相框',33:'金色月牙',34:'粉色魔杖',36:'金色星轨',38:'紫色徽章',39:'金色星光',40:'绿色藤蔓',41:'樱花团子',42:'细线边框',45:'粉色边框',46:'猫耳相框',47:'红心摆饰',48:'红玫瑰',49:'白色花框',50:'花纹手机框',51:'桃花相框',52:'星星光点',53:'古典相框',54:'蓝色相框',55:'橙色相框',56:'淡绿相框',57:'浅蓝相框',58:'玫瑰挂坠框',59:'金色挂坠框',60:'甜点气泡',61:'白色手机外框',62:'粉色卷线',63:'白色星光',64:'手势摆饰',65:'轻触手势',66:'爱心手势',67:'灰色手机框',68:'斜纹边框',69:'暗色雕花框',70:'金色小星',71:'深色手机框',72:'花色手机框',73:'白色手机边框',74:'淡红光点'}

TERMS={'witch': '巫师帽', 'sun hat': '遮阳帽', 'straw': '草帽', 'hairpin': '发簪', 'hairclip': '发夹', 'hairclips': '发夹', 'bowlerhat': '圆顶礼帽', 'bow': '蝴蝶结', 'beanie': '针织帽', 'beret': '贝雷帽', 'cap': '帽子', 'hood': '兜帽', 'bonnet': '软帽', 'headband': '发箍', 'hat': '帽子', 'ribbon': '丝带', 'scarf': '围巾', 'cashmere': '羊绒', 'flannel': '法兰绒', 'wool': '羊毛', 'necklace': '项链', 'pendant': '吊坠', 'amulet': '护符', 'choker': '颈饰', 'tie': '领带', 'bracelet': '手链', 'gloves': '手套', 'mittens': '连指手套', 'warmers': '保暖套', 'socks': '袜子', 'stockings': '长袜', 'tights': '连裤袜', 'leggings': '打底裤', 'boots': '靴子', 'heels': '跟鞋', 'trainers': '运动鞋', 'sneakers': '休闲鞋', 'sandals': '凉鞋', 'loafers': '乐福鞋', 'pumps': '浅口鞋', 'shoes': '鞋子', 'slippers': '拖鞋', 'wellies': '雨靴', 'clogs': '木屐', 'flippers': '潜水脚蹼', 'geta': '木屐', 'zori': '草履', 'earmuffs': '耳罩', 'earrings': '耳环', 'earpiece': '耳饰', 'tiara': '头冠', 'crown': '冠饰', 'glasses': '眼镜', 'shades': '墨镜', 'eyepatch': '眼罩', 'mask': '面具', 'goggles': '护目镜', 'aviator': '飞行镜', 'monocle': '单片镜', 'surgical': '医用', 'reading': '阅读镜', 'deepframe': '深框眼镜', 'lowframe': '低框眼镜', 'halfmoon': '半月镜', 'cateye': '猫眼眼镜', 'cool': '酷炫', 'gasmask': '防护面罩', 'round': '圆形', 'square': '方形', 'fox': '狐狸', 'cat': '猫咪', 'bunny': '兔子', 'bear': '小熊', 'butterfly': '蝴蝶', 'flower': '花朵', 'rose': '玫瑰', 'tulip': '郁金香', 'daisy': '雏菊', 'apple': '苹果', 'star': '星星', 'heart': '爱心', 'gold': '金色', 'silver': '银色', 'copper': '铜色', 'blue': '蓝色', 'pink': '粉色', 'white': '白色', 'black': '黑色', 'green': '绿色', 'red': '红色', 'purple': '紫色', 'yellow': '黄色', 'christmas': '圣诞', 'snow': '雪花', 'winter': '冬季', 'summer': '夏季', 'fur': '毛绒', 'fuzzy': '毛绒', 'floral': '花纹', 'lace': '蕾丝', 'striped': '条纹', 'plain': '素色', 'long': '长款', 'short': '短款', 'knee': '及膝', 'thighhigh': '过膝', 'ankle': '脚踝', 'sports': '运动', 'gym': '运动', 'work': '工作', 'combat': '战斗', 'football': '足球', 'school': '学校', 'chef': '厨师', 'sailor': '水手', 'military': '军旅', 'cowboy': '牛仔', 'nun': '修女', 'nurse': '护士', 'maid': '女仆', 'gothic': '哥特', 'night': '睡眠', 'sleeping': '睡眠', 'umbrella': '雨伞', 'parasol': '阳伞', 'backpack': '背包', 'purse': '手袋', 'suitcase': '行李箱', 'luggage': '行李', 'compass': '罗盘', 'coin': '硬币', 'key': '钥匙', 'bottle': '瓶子', 'cup': '杯子', 'box': '盒子', 'candy': '糖果', 'cane': '手杖', 'sword': '剑', 'blade': '刀刃', 'dagger': '匕首', 'broom': '扫帚', 'fishing rod': '钓竿', 'fan': '扇子', 'pinwheel': '风车', 'talisman': '护符', 'gem': '宝石', 'crystal': '水晶', 'cocoa': '可可', 'cider': '苹果饮品', 'chocolate': '巧克力', 'watering can': '浇水壶', 'milk': '牛奶', 'tea': '茶叶', 'feather': '羽毛', 'pompom': '绒球', 'medical': '医疗', 'antique': '古典', 'base': '基础', 'leather': '皮革', 'conical': '尖顶', 'wide brim': '宽檐', 'balloon': '气球', 'book': '书本'}

def apply(pack:Path):
 p=pack/'ui/sprites.json';sheet=json.loads(p.read_text(encoding='utf-8'))
 w=pack/'wardrobe.json';wardrobe=json.loads(w.read_text(encoding='utf-8'))
 for key,slot in wardrobe['slots'].items():
  if key in ('upper','lower'):continue
  suffix={'headwear':'帽饰','facewear':'面饰','neckwear':'项链','handwear':'手饰','legwear':'袜饰','footwear':'鞋子','earrings':'耳环','fingerwear':'戒指','handheld':'持物'}.get(key,'饰品')
  for value,label in slot['items'].items():
   gem=next((human for name,human in GEMS.items() if name in value),None)
   if gem and label==value:slot['items'][value]=gem+suffix+' · '+value
   elif label==value and value!='none':
    human=value.casefold()
    for token in sorted(TERMS,key=len,reverse=True):human=human.replace(token,TERMS[token])
    human=re.sub(r"[a-z0-9 _.'-]+",'',human)
    slot['items'][value]=(human or suffix)+' · '+value
  if key=='earrings' and 'graphic' in slot['items']:slot['items']['graphic']='图案耳环（花朵、星月、小动物）'
  sheet['labels'][key]=slot['items']
 if 'earring_graphic' in sheet['controls']:
  for value in sheet['controls']['earring_graphic']:
   human=value
   for token in sorted(TERMS,key=len,reverse=True):human=human.replace(token,TERMS[token])
   human=re.sub(r"[a-z0-9 _.'-]+",'',human)
   sheet['controls']['earring_graphic'][value]=(human+' · '+value) if human else value
 for key,options in sheet['controls'].items():
  if not key.startswith('decoration_'):continue
  for value in list(options):
   if value=='none':continue
   group,number=value.rsplit('-',1);n=int(number)
   if group=='background1':name=SCENES[n-1] if n<=len(SCENES) else '场景背景'
   elif group=='background':name={1:'黑色披风摆饰',2:'海面日出',3:'秋日庭院',4:'月光卧室',5:'紫色夜窗',6:'粉色街景',7:'木屋壁灯'}.get(n,'背景摆饰')
   elif group=='background2':name={1:'花丛摆饰',2:'古典屏风',3:'黑色披风摆饰',4:'紫色藤椅',5:'灰色地台',6:'白色地台',7:'金色光环',8:'木色地台',9:'花纹地毯',10:'红色地毯',11:'粉色格纹',12:'紫色光晕'}.get(n,'场景背景')
   else:name=FG.get(n, '持手机手势' if 75<=n<=89 else '彩色手机边框' if n>=100 else '前景摆饰')
   options[value]=name+' · '+value
 p.write_text(json.dumps(sheet,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
 w.write_text(json.dumps(wardrobe,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--pack',type=Path,required=True);apply(parser.parse_args().pack)
