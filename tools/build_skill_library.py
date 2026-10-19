"""Build the authored 300-entry, data-only martial/magic example ZIP deterministically."""
from __future__ import annotations
import json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for sub in ("core","content"):sys.path.insert(0,str(ROOT/sub))
from rpg_content.skill_library import SkillLibrary,SkillLibraryManifest,LibrarySkill,RESOURCE_ALIASES

# Each school has five distinct actions and three named levels, not numbered duplicates.
MARTIAL = [
("sword","剑术","直刺|横斩|挑剑|架剑|收势","连环刺|掠风斩|撩腕剑|转身格|追步剑","破隙连刺|回锋叠斩|截势夺线|守中反击|游龙贯势",[
("送剑尖试探正面空隙并立即收回","刺击单个近身目标","enemy"),("用剑刃横向划过对手暴露的防线","切入侧面防线","enemy"),("由下而上挑开接近的兵刃","改变对方兵刃方向","enemy"),("将剑身斜置并侧步卸开来击","格挡一次可见攻击","self"),("收拢剑势并调整脚步距离","重建攻守距离","self")]),
("blade","刀术","劈刀|抹刀|截刀|拦刀|拖步刀","沉锋劈|回身抹|抢势截|盘刀护|进步连刀","开势重劈|回环斩|断势截锋|八面护锋|逐隙追刀",[
("沉肩挥刀劈向对手露出的防线","施加正面压迫","enemy"),("贴近后短促抽动刀刃并及时撤身","近身短幅切击","enemy"),("在对手动作尚未展开时出刀截住来路","打断明显的起手","enemy"),("以刀背配合身法挡开逼近的攻击","保护持刀侧","self"),("用跟进脚步维持刀锋的有效距离","追随正在后退的目标","enemy")]),
("spear","枪术","平扎|拨枪|拦枪|点步枪|回枪","连点枪|绕杆拨|缠拦枪|滑步扎|回马探枪","贯隙长枪|盘龙夺杆|锁线拦枪|追影贯刺|回锋定枪",[
("沿直线送出枪尖并保留回收距离","利用长兵器距离刺击","enemy"),("用枪杆侧拨对方兵刃","偏移进攻路线","enemy"),("横杆拦住来势后退开半步","阻拦接近","self"),("小步调整站位后以枪尖点向破绽","移动中保持距离","enemy"),("回撤枪尖并转向侧后方警戒","处理绕侧威胁","self")]),
("bow","弓术","定身射|近距速射|仰角射|听风瞄|持弓稳息","移动择机射|双矢换靶|越障抛射|测风修正|长持蓄势","穿隙精准射|连靶压制|高差曲射|逆风定弦|沉息远射",[
("搭箭拉弦，稳定姿势后瞄准可见目标放箭","对视线内单个目标射击","enemy"),("缩短瞄准过程，在安全距离内快速放箭","压迫近处可见目标","enemy"),("估算高差后让箭越过低矮遮挡","尝试曲线射击","enemy"),("观察风向并修正箭尖朝向","改善下一次射击判断","self"),("放缓呼吸并稳定持弓的手臂","维持瞄准稳定","self")]),
("staff","棍杖","平扫棍|点杆|横架棍|下拦棍|撑杆退步","连环扫|短打点杆|旋杆护身|绕膝拦棍|借杆换位","破围横扫|寸距穿杆|圆守反打|截步锁棍|借势游杆",[
("握紧棍杆横扫近处空隙并及时回收","控制身前近处空间","enemy"),("将棍端短促送向对手防线","用短幅动作试探","enemy"),("横起棍杆并用后退分散冲击","架开正面来击","self"),("用棍杆压低拦住下段逼近","防范低位进攻","self"),("以棍杆支撑平衡后退向空处","在受压时改变站位","self")]),
("fist","拳掌","直拳|掌推|肘护|低踢|架势稳身","双连拳|卸力掌|贴身肘架|换步踢|沉身蓄力","破隙寸拳|转劲推掌|缠身护肘|截步连踢|整劲贯身",[
("护住面部并短促送出直拳","攻击单个近身目标","enemy"),("以掌根推向对手重心并及时撤掌","扰动对方平衡","enemy"),("收肘护住躯干并移动躲开正面冲击","近身防护","self"),("保持自身平衡后踢向对手低位空隙","限制对方步法","enemy"),("调整站姿与呼吸，将重心沉稳落地","恢复稳定架势","self")]),
("grapple","擒拿","脱腕|扣臂|绊步|抱架|护摔","旋腕解扣|绕肘控臂|换位牵绊|贴身抱架|借势滚卸","连环解缚|锁线控身|夺衡摔投|破抱反控|落地复位",[
("沿抓握薄弱处旋转手腕并抽回手臂","脱离一次手部抓握","self"),("抓住对手手臂并限制其转动方向","近身控制而非必定制服","enemy"),("配合牵引试探对手落脚重心","尝试使对方失衡","enemy"),("贴近对手并保持躯干架势","限制近身活动空间","enemy"),("收拢下颌并沿地面滚动分散冲击","减轻可预见摔落冲击","self")]),
("footwork","身法","侧步|后撤步|伏身闪|跨障|轻步","交错步|撤转步|俯身换线|借沿跨越|静步绕行","游隙步|脱围换位|贴势避锋|连障穿行|无声择路",[
("观察空位并向侧面移开身体","避开一条可见攻击线","self"),("保持正面警戒并后撤拉开距离","脱离近身压迫","self"),("屈膝降低身体并侧向闪开","躲避高位来势","self"),("判断落点后跨过低矮障碍","通过可达的地形障碍","scene"),("缓慢落脚，避开容易发声的地面","降低普通移动声音","self")]),
("shield","盾术","举盾|盾推|贴盾进|护侧|蹲盾","斜盾卸力|进身盾撞|掩盾换步|转盾护侧|低身盾守","定面壁守|破势盾冲|连步掩进|环身护阵|伏盾承压",[
("将盾面对准威胁并稳住持盾手","阻挡盾面可覆盖方向","self"),("在站稳后以盾面推向近处对手","迫使对方调整重心","enemy"),("借盾面遮护小步前进","在掩护下缩短距离","self"),("随威胁方向转动盾面","保护暴露的身体侧面","self"),("屈膝缩小身体暴露范围","对低位冲击建立防护","self")]),
("throwing","投掷","掷石|短距投镖|抛绳|扰目投物|稳手瞄点","连石换角|转腕投镖|绕柱抛绳|声东投物|移步择点","破隙精掷|连镖封线|牵绳缠绕|多点佯投|远距定点",[
("掂量手中石块后投向视线内目标","投掷普通小物件","enemy"),("用短促腕力送出适合投掷的小型器具","近距精准投掷","enemy"),("估算距离后将绳头抛向可见支点","尝试建立绳索连接","scene"),("将小物投向侧方以制造可察觉的动静","分散普通观察者注意","scene"),("观察距离与遮挡后稳定投掷手势","判断投掷落点","self")]),
]
MAGIC = [
("fire","火焰","火弹|引火术|焰线|小火盾|温感术","炎矢|驭焰术|缠焰带|旋焰屏|热迹探知","日珥矢|织火阵|环焰锁路|叠焰守壁|余烬寻迹",[
("借咒语在媒介前凝聚一小团火焰后送出","火焰冲击单个可见目标","enemy"),("触碰安全燃料附近的媒介并引出火苗","点燃合适的可燃物","scene"),("在可见空地上引导一段短火线","限制一条近处路线","scene"),("在身前维持可承受短暂来势的火焰薄层","暂时缓冲轻微冲击","self"),("通过媒介感受附近热量差异","察觉可感知的热源","scene")]),
("frost","冰霜","冰针|薄冰障|霜地术|凝露术|寒感术","霜矛|叠冰墙|滑霜径|凝水结晶|冰痕追感","寒晶贯矛|棱冰守墙|霜域限行|寒晶塑形|封霜寻迹",[
("念咒使媒介周围水汽凝成短冰针后推出","冷击单个可见目标","enemy"),("在前方凝出一层有限厚度的薄冰","阻挡轻型来物","scene"),("在近处湿润地面凝出薄霜","改变局部地面摩擦","scene"),("将可接触的少量水汽聚拢并凝结","收集有限的凝结水","item"),("感受周围气流和物体表面的寒意","判断可感知的低温方向","scene")]),
("wind","风息","风刃|推风术|顺风步|听风术|散尘术","回旋风刃|束流推送|借风换步|风隙听音|清风卷尘","连弧风刃|回流风道|驭风长跃|远风辨位|环流净道",[
("以媒介引导一束短促气流掠向空隙","用气流压迫可见目标","enemy"),("挥动媒介将近处气流推向指定方向","推动轻小松散物件","scene"),("念咒让顺向气流轻托脚步","辅助普通移动而非凭空飞行","self"),("放缓呼吸借气流分辨附近声音","辅助辨认声音方向","scene"),("控制小股风将面前浮尘吹离视线","改善局部可见度","scene")]),
("earth","岩土","石弹|矮土墙|固地术|岩肤术|塑泥术","碎岩矢|叠土垒|稳基法|砂岩护肤|泥构塑形","棱岩重矢|环垒土壁|定域固基|叠岩护身|地构匠形",[
("借媒介从已有碎石中抬起一块并推出","投出已有岩石","enemy"),("在可操控的松土上隆起一道矮墙","制造局部低矮遮挡","scene"),("让脚边可接触的松软地面变得紧实","稳定有限区域地面","scene"),("以少量沙土形成贴身的临时护层","缓解轻微擦碰","self"),("揉塑已有湿泥，使其形成简单形状","制作非精密的泥质物件","item")]),
("water","流水","水矢|水幕|净水术|导流术|薄雾术","涌流矢|回环水幕|澄水术|分流引渠|弥雾遮形","旋涡水矢|叠流护幕|深澄净水|水脉导引|流雾迷径",[
("将身边已有清水聚成水束并向前送出","冲击单个近处目标","enemy"),("以已有水源在身前张开短暂水幕","缓冲轻微飞溅和来物","self"),("通过法阵沉降少量水中可分离的杂质","改善普通浑水而非保证除毒","item"),("引导已有浅水沿低处缓慢流动","改变局部小股水流方向","scene"),("将已有水分化成一层薄雾","遮蔽局部普通视线","scene")]),
("thunder","雷电","电弧|静电护|雷鸣声|感电术|蓄雷印","跃电矢|绕电护层|定向雷鸣|电迹追感|蕴雷符","链弧雷矢|叠雷护环|震雷回响|雷息辨踪|回雷阵印",[
("借导引媒介放出一小段受控电弧","电击单个可见目标","enemy"),("在媒介周围维持有限的带电防护层","威慑近身触碰","self"),("让空气中发出受控的雷鸣般响声","制造信号或分散注意","scene"),("通过媒介感知近处异常电性变化","探察可感知的电性痕迹","scene"),("在合适媒介上保留短暂的受控雷息","为后续仪式维持有限能量","item")]),
("light","光辉","点灯术|微光箭|愈合术|明视术|驱晦术","长明灯|辉光矢|舒创术|辨影之眼|净晦光环","星辉长明|凝辉贯矢|回生抚创|澄明远视|晨辉净障",[
("念咒在媒介顶端凝出稳定柔光","照亮有限范围并作为信号","scene"),("凝聚一道可见光束向前方空隙射出","光辉冲击单个目标","enemy"),("以柔和光辉覆住可接触的浅表伤处","缓解轻微创伤，不能直接再生肢体","ally"),("将微光汇入视线周围并缓缓观察","辅助辨认昏暗处轮廓","self"),("用温和辉光照向轻微的晦暗干扰","削弱普通阴影遮蔽，不保证破除诅咒","scene")]),
("ward","结界","小型屏障|警戒符|稳阵术|净障印|护物纹","多面屏障|回响警戒|连结法阵|解扰法印|封护纹","叠层守壁|环域警戒|谐振稳阵|澄界法印|久守封纹",[
("用媒介画出勉强罩住自身的有限光盾","短暂格挡或缓冲可承受的冲击","self"),("在可接触表面留下会对明显接近作出反应的符印","建立有限范围的普通警戒","scene"),("检查并稳住一个已知的小型法阵结构","缓解已知法阵的轻微紊乱","scene"),("沿现有纹路画出温和的消扰印记","尝试削弱轻微魔力干扰","scene"),("在已有小物件上画出临时防护纹路","减轻轻微环境磨损","item")]),
("illusion","幻术","虚像术|拟声术|敛影术|拟色术|偏光术","连影幻像|回声拟音|藏影步|随景拟色|折光扰向","镜阵幻像|远声投影|隐息藏形|移景幻衣|迷光回廊",[
("借媒介投出一个不具实体的简单影像","短暂影响普通视觉判断","scene"),("在近处投出一段简单而非思想控制的拟声","制造有限声音误导","scene"),("以轻微暗影柔化自身的显眼轮廓","降低普通观察时的显眼程度","self"),("将表面颜色暂时调整得接近周围环境","获得有限的视觉伪装","self"),("让一小片光线轻微偏折以扰动方向感","干扰普通目视瞄准","enemy")]),
("space","空间","口袋术|短距换位|空间标记|封隙术|探隙术","折叠收纳|定点换位|双点锚记|稳隙法|隙外窥视","袖界收纳|连锚跃迁|多点航标|界缝封护|界路探知",[
("在允许空间法术的媒介中展开一个有限收纳夹层","收纳小型非生命物件","item"),("确认近处安全落点后借媒介尝试短距位置交换","短距换位，受封锁和视线规则约束","self"),("在可接触地点留下可辨认的空间印记","记录一个已到达的空间锚点","scene"),("沿已存在的小型空间裂隙边缘施加稳定纹路","尝试暂时稳住轻微空间紊乱","scene"),("通过已知安全裂隙感受另一侧的有限迹象","探察已存在的微小空间缝隙","scene")]),
]


def build():
    entries=[]
    for kind,schools in (("martial",MARTIAL),("magic",MAGIC)):
        for school,label,low,mid,high,actions in schools:
            names=[low.split("|"),mid.split("|"),high.split("|")]
            for level,tier in enumerate(("low","mid","high")):
                for index,(action,effect,target) in enumerate(actions):
                    name=names[level][index]
                    if level == 1:
                        action += "，衔接一次变招并保留收势余地" if kind == "martial" else "，在持续施法中微调作用形态与方向"
                        effect += "，提高移动或干扰下的稳定性"
                    elif level == 2:
                        action += "，依据对手反应连续转换攻守节奏" if kind == "martial" else "，以复合术式协调多个相近作用点"
                        effect += "，支持复杂局面下的连续控制"
                    key=f"{kind}_{school}_{tier}_{index+1:02d}"
                    parent=[] if level==0 else [f"{kind}_{school}_{('low','mid')[level-1]}_{index+1:02d}"]
                    grade=("低级","中级","高级")[level]
                    precision=("以单次、短距、有限范围完成基础动作", "在移动或干扰下保持稳定，可在合理范围内串联动作", "在复杂局面下保持熟练控制，范围和效果仍受世界规则、资源及防护限制")[level]
                    equipment=("需要合适且实际持有的器具；无器具时不能凭空生成" if school not in ("fist","grapple","footwork") else "需要身体能正常活动，受伤或地形不利时效果会降低") if kind=="martial" else "需要本世界认可的咒语、法阵或施法媒介；不绕过禁魔、距离及目标条件"
                    instruction=f"固定行动：{action}。预定效果：{effect}。熟练层级：{precision}。适用条件：{equipment}。框架已收取 resource_cost 对应消耗，不再次收取同一笔。命中、对抗和额外环境后果按现有结算规则处理，不将敌方伤害记到玩家生命上。"
                    cost=(1+level*2+(index%2) if kind=="magic" else 1+level+(1 if level==2 and index<2 else 0))
                    aliases={"magic_fire_low_01":["火球术","小火球"],"magic_light_low_01":["照明术"],"magic_ward_low_01":["护盾术"]}.get(key,[])
                    entry={"id":key,"kind":kind,"tier":tier,"school":label,
                        "tags":[label,"武技" if kind=="martial" else "魔法",grade,"防御" if target=="self" else "战斗" if target=="enemy" else "探索"],
                        "aliases":aliases,"requires_world_tags":([] if kind=="martial" else ["magic"]+(["spatial_magic"] if school=="space" else [])),
                        "excludes_world_tags":["no_magic"] if kind=="magic" else [],
                        "prerequisites":parent,"resource_cost":{"effort" if kind=="martial" else "mana":cost},"instruction":instruction,
                        "skill":{"id":key,"name":name,"description":f"{grade}{label}。{action}，{effect}。", "cost":{},"cooldown":level+(1 if index in (2,3) else 0),
                            "targets":[target],"usable_when":equipment,"action_text":f"我施展{name}，{action}。",
                            "effect_hint":effect,"category":f"{'武技' if kind=='martial' else '魔法'} · {grade}","brief":effect[:22]}}
                    entries.append(entry)
    lib=SkillLibrary(manifest={"type":"rpg.skill-library","schema_version":1,"id":"standard-martial-magic","title":"武技与魔法标准技能库·300","version":"1.0.0","description":"150个武技、150个魔法；每类低/中/高各50。初始掌握数量由角色背景决定。","resources":RESOURCE_ALIASES},skills=entries)
    assert len(lib.skills)==300 and len({e.skill.name for e in lib.skills})==300
    dest=ROOT/'skill-libraries/standard-300';dest.mkdir(parents=True,exist_ok=True)
    (dest/'manifest.json').write_text(json.dumps(lib.manifest.model_dump(mode='json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dest/'skills.json').write_text(json.dumps({'skills':[s.model_dump(mode='json') for s in lib.skills]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    readme = """# 技能库格式 v1

ZIP 根目录或唯一一层文件夹内放 manifest.json 和 skills.json。
manifest.type 必须为 rpg.skill-library，schema_version=1，id 使用小写字母/数字/连字符。
skills.json 为 {"skills": [条目]}；每项含 id、kind(martial/magic)、tier(low/mid/high)、school、tags、aliases、requires_world_tags、excludes_world_tags、prerequisites、resource_cost、instruction、skill。
skill 是完整技能定义：id/name/description/cost/cooldown/targets/usable_when/action_text/effect_hint/category/brief。
条目 id 与 skill.id 必须相同；skill.cost 留空，消耗由 resource_cost 声明，再依据 manifest.resources 绑定游戏状态字段。
默认 effort 优先 stamina/energy/focus；mana 优先 mp/mana/focus；资源字段缺失的技能不会变成免费技能。
魔法必须 requires_world_tags 包含 magic。prerequisites 引用同库条目 id，不能循环。
学习只引用 ref（库id:条目id），不重写预设技能；初始掌握数量由世界和角色背景决定，没有固定新手配额。
本包仅包含数据，不放 Python、JavaScript、插件或可执行指令脚本。instruction 是给叙事/结算模型的固定行动说明。
升级请采用新的库 id，旧世界保留自己的快照，不覆盖旧技能定义。

导入：设置 → 技能库 · 预设技能 → 导入技能库 ZIP。
随后新建世界会自动匹配；已有可编辑世界可点“为当前世界匹配技能池”，保留当前进度。
已掌握技能可以直接勾选使用，未掌握技能由叙述确认学习后由后端登记。
"""
    (dest/'README.md').write_text(readme,encoding='utf-8')
    (dest/'manifest.schema.json').write_text(json.dumps(SkillLibraryManifest.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dest/'skill.schema.json').write_text(json.dumps(LibrarySkill.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def archive_folder(folder,output):
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for file in sorted(folder.iterdir()):
                if file.is_file():
                    info=zipfile.ZipInfo(folder.name+'/'+file.name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                    archive.writestr(info,file.read_bytes(),compresslevel=9)
    zip_path=ROOT/'skill-libraries/standard-300.zip'
    archive_folder(dest,zip_path)
    template=ROOT/'skill-libraries/author-template';template.mkdir(exist_ok=True)
    example=lib.skills[105].model_dump(mode='json')
    example['id']='steady_step';example['skill']['id']='steady_step';example['skill']['name']='稳步';example['skill']['action_text']='我收拢步幅，稳住重心。';example['prerequisites']=[]
    example_lib=SkillLibrary(manifest={**lib.manifest.model_dump(mode='json'),'id':'custom-skills-example','title':'作者自定义技能库示例','description':'复制目录、修改内容与库 id 后打成 ZIP 导入。'},skills=[example])
    (template/'manifest.json').write_text(json.dumps(example_lib.manifest.model_dump(mode='json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (template/'skills.json').write_text(json.dumps({'skills':[e.model_dump(mode='json') for e in example_lib.skills]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for filename in ('README.md','manifest.schema.json','skill.schema.json'):(template/filename).write_bytes((dest/filename).read_bytes())
    archive_folder(template,ROOT/'skill-libraries/author-template.zip')
    (ROOT/'skill-libraries/README.md').write_text(readme,encoding='utf-8')
    print(f'Created {len(lib.skills)} unique skills: {zip_path.name} ({zip_path.stat().st_size} bytes)')
    return lib
if __name__=='__main__':build()
