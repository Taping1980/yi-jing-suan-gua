"""
兵器破阵 · 易经起卦 — 后端服务
FastAPI + SQLite + 64卦完整数据 + AI 解卦（DeepSeek）
"""
import os
import json
import random
import hashlib
import sqlite3
import datetime
from typing import Optional
from contextlib import contextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ==================== 配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "yijing.db")
DEEPSEEK_API_KEY = "sk-3fc49d4957d54a24b07c9ec866713bbb"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

app = FastAPI(title="兵器破阵 · 易经起卦")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 静态文件服务
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

# 根路径返回index.html
@app.get("/")
async def read_root():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

# ==================== 数据库 ====================
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,        -- 设备指纹 hash
                nickname TEXT DEFAULT '无名修士',
                level INTEGER DEFAULT 1,    -- 道行等级
                exp INTEGER DEFAULT 0,      -- 修炼经验
                spirit INTEGER DEFAULT 10,  -- 灵力
                signin_date TEXT,           -- 上次签到日期
                signin_streak INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS weapons (
                user_id TEXT,
                weapon_id TEXT,
                level INTEGER DEFAULT 1,    -- 强化等级
                unlocked INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, weapon_id)
            );
            CREATE TABLE IF NOT EXISTS divinations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                weapon_id TEXT,
                question TEXT,
                hexagram_origin INTEGER,    -- 本卦编号 1-64
                hexagram_changed INTEGER,   -- 变卦编号 (0=无变卦)
                changing_lines TEXT,        -- 动爻位置, 逗号分隔
                judgment TEXT,              -- AI 解读结果
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS achievements (
                user_id TEXT,
                ach_id TEXT,
                unlocked_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (user_id, ach_id)
            );
            CREATE TABLE IF NOT EXISTS daily_stats (
                user_id TEXT,
                date TEXT,
                divination_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            );
            CREATE TABLE IF NOT EXISTS daily_tasks (
                user_id TEXT,
                date TEXT,
                task_id TEXT,
                progress INTEGER DEFAULT 0,
                target INTEGER DEFAULT 1,
                claimed INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date, task_id)
            );
        """)

# ==================== 64卦完整数据 ====================
HEXAGRAMS = {
    1:  {"name":"乾为天",  "symbol":"䷀", "upper":"乾","lower":"乾",
         "judgment":"元亨利贞。", "image":"天行健，君子以自强不息。",
         "lines":["潜龙勿用。","见龙在田，利见大人。","君子终日乾乾，夕惕若厉，无咎。","或跃在渊，无咎。","飞龙在天，利见大人。","亢龙有悔。"]},
    2:  {"name":"坤为地",  "symbol":"䷁", "upper":"坤","lower":"坤",
         "judgment":"元亨，利牝马之贞。君子有攸往，先迷后得主，利。西南得朋，东北丧朋。安贞吉。",
         "image":"地势坤，君子以厚德载物。",
         "lines":["履霜，坚冰至。","直方大，不习无不利。","含章可贞，或从王事，无成有终。","括囊，无咎无誉。","黄裳，元吉。","龙战于野，其血玄黄。"]},
    3:  {"name":"水雷屯",  "symbol":"䷂", "upper":"坎","lower":"震",
         "judgment":"元亨利贞。勿用有攸往，利建侯。", "image":"云雷屯，君子以经纶。",
         "lines":["磐桓，利居贞，利建侯。","屯如邅如，乘马班如。匪寇婚媾，女子贞不字，十年乃字。","即鹿无虞，惟入于林中，君子几不如舍，往吝。","乘马班如，求婚媾，往吉，无不利。","屯其膏，小贞吉，大贞凶。","乘马班如，泣血涟如。"]},
    4:  {"name":"山水蒙",  "symbol":"䷃", "upper":"艮","lower":"坎",
         "judgment":"亨。匪我求童蒙，童蒙求我。初筮告，再三渎，渎则不告。利贞。",
         "image":"山下出泉，蒙。君子以果行育德。",
         "lines":["发蒙，利用刑人，用说桎梏，以往吝。","包蒙，吉。纳妇，吉。子克家。","勿用取女，见金夫，不有躬，无攸利。","困蒙，吝。","童蒙，吉。","击蒙，不利为寇，利御寇。"]},
    5:  {"name":"水天需",  "symbol":"䷄", "upper":"坎","lower":"乾",
         "judgment":"有孚，光亨，贞吉。利涉大川。", "image":"云上于天，需。君子以饮食宴乐。",
         "lines":["需于郊，利用恒，无咎。","需于沙，小有言，终吉。","需于泥，致寇至。","需于血，出自穴。","需于酒食，贞吉。","入于穴，有不速之客三人来，敬之终吉。"]},
    6:  {"name":"天水讼",  "symbol":"䷅", "upper":"乾","lower":"坎",
         "judgment":"有孚，窒惕，中吉，终凶。利见大人，不利涉大川。",
         "image":"天与水违行，讼。君子以作事谋始。",
         "lines":["不永所事，小有言，终吉。","不克讼，归而逋，其邑人三百户，无眚。","食旧德，贞厉，终吉。或从王事，无成。","不克讼，复即命，渝安贞，吉。","讼，元吉。","或锡之鞶带，终朝三褫之。"]},
    7:  {"name":"地水师",  "symbol":"䷆", "upper":"坤","lower":"坎",
         "judgment":"贞，丈人吉，无咎。", "image":"地中有水，师。君子以容民畜众。",
         "lines":["师出以律，否臧凶。","在师中，吉无咎，王三锡命。","师或舆尸，凶。","师左次，无咎。","田有禽，利执言，无咎。长子帅师，弟子舆尸，贞凶。","大君有命，开国承家，小人勿用。"]},
    8:  {"name":"水地比",  "symbol":"䷇", "upper":"坎","lower":"坤",
         "judgment":"吉。原筮，元永贞，无咎。不宁方来，后夫凶。",
         "image":"地上有水，比。先王以建万国，亲诸侯。",
         "lines":["有孚比之，无咎。有孚盈缶，终来有他，吉。","比之自内，贞吉。","比之匪人。","外比之，贞吉。","显比，王用三驱，失前禽。邑人不诫，吉。","比之无首，凶。"]},
    9:  {"name":"风天小畜","symbol":"䷈", "upper":"巽","lower":"乾",
         "judgment":"亨。密云不雨，自我西郊。", "image":"风行天上，小畜。君子以懿文德。",
         "lines":["复自道，何其咎，吉。","牵复，吉。","舆说辐，夫妻反目。","有孚，血去惕出，无咎。","有孚挛如，富以其邻。","既雨既处，尚德载，妇贞厉。月几望，君子征凶。"]},
    10: {"name":"天泽履",  "symbol":"䷉", "upper":"乾","lower":"兑",
         "judgment":"履虎尾，不咥人，亨。", "image":"上天下泽，履。君子以辨上下，定民志。",
         "lines":["素履，往无咎。","履道坦坦，幽人贞吉。","眇能视，跛能履，履虎尾，咥人，凶。武人为于大君。","履虎尾，愬愬终吉。","夬履，贞厉。","视履考祥，其旋元吉。"]},
    11: {"name":"地天泰",  "symbol":"䷊", "upper":"坤","lower":"乾",
         "judgment":"小往大来，吉亨。", "image":"天地交，泰。后以财成天地之道，辅相天地之宜，以左右民。",
         "lines":["拔茅茹，以其汇，征吉。","包荒，用冯河，不遐遗，朋亡，得尚于中行。","无平不陂，无往不复，艰贞无咎。勿恤其孚，于食有福。","翩翩，不富以其邻，不戒以孚。","帝乙归妹，以祉元吉。","城复于隍，勿用师，自邑告命，贞吝。"]},
    12: {"name":"天地否",  "symbol":"䷋", "upper":"乾","lower":"坤",
         "judgment":"否之匪人，不利君子贞，大往小来。", "image":"天地不交，否。君子以俭德辟难，不可荣以禄。",
         "lines":["拔茅茹，以其汇，贞吉亨。","包承，小人吉，大人否亨。","包羞。","有命无咎，畴离祉。","休否，大人吉。其亡其亡，系于苞桑。","倾否，先否后喜。"]},
    13: {"name":"天火同人","symbol":"䷌", "upper":"乾","lower":"离",
         "judgment":"同人于野，亨。利涉大川，利君子贞。", "image":"天与火，同人。君子以类族辨物。",
         "lines":["同人于门，无咎。","同人于宗，吝。","伏戎于莽，升其高陵，三岁不兴。","乘其墉，弗克攻，吉。","同人先号咷而后笑，大师克相遇。","同人于郊，无悔。"]},
    14: {"name":"火天大有","symbol":"䷍", "upper":"离","lower":"乾",
         "judgment":"元亨。", "image":"火在天上，大有。君子以遏恶扬善，顺天休命。",
         "lines":["无交害，匪咎，艰则无咎。","大车以载，有攸往，无咎。","公用亨于天子，小人弗克。","匪其彭，无咎。","厥孚交如，威如，吉。","自天佑之，吉无不利。"]},
    15: {"name":"地山谦",  "symbol":"䷎", "upper":"坤","lower":"艮",
         "judgment":"亨，君子有终。", "image":"地中有山，谦。君子以裒多益寡，称物平施。",
         "lines":["谦谦君子，用涉大川，吉。","鸣谦，贞吉。","劳谦君子，有终吉。","无不利，撝谦。","不富以其邻，利用侵伐，无不利。","鸣谦，利用行师，征邑国。"]},
    16: {"name":"雷地豫",  "symbol":"䷏", "upper":"震","lower":"坤",
         "judgment":"利建侯行师。", "image":"雷出地奋，豫。先王以作乐崇德，殷荐之上帝，以配祖考。",
         "lines":["鸣豫，凶。","介于石，不终日，贞吉。","盱豫，悔。迟有悔。","由豫，大有得。勿疑，朋盍簪。","贞疾，恒不死。","冥豫，成有渝，无咎。"]},
    17: {"name":"泽雷随",  "symbol":"䷐", "upper":"兑","lower":"震",
         "judgment":"元亨利贞，无咎。", "image":"泽中有雷，随。君子以向晦入宴息。",
         "lines":["官有渝，贞吉。出门交有功。","系小子，失丈夫。","系丈夫，失小子。随有求得，利居贞。","随有获，贞凶。有孚在道，以明，何咎。","孚于嘉，吉。","拘系之，乃从维之。王用亨于西山。"]},
    18: {"name":"山风蛊",  "symbol":"䷑", "upper":"艮","lower":"巽",
         "judgment":"元亨，利涉大川。先甲三日，后甲三日。", "image":"山下有风，蛊。君子以振民育德。",
         "lines":["干父之蛊，有子，考无咎，厉终吉。","干母之蛊，不可贞。","干父之蛊，小有悔，无大咎。","裕父之蛊，往见吝。","干父之蛊，用誉。","不事王侯，高尚其事。"]},
    19: {"name":"地泽临",  "symbol":"䷒", "upper":"坤","lower":"兑",
         "judgment":"元亨利贞。至于八月有凶。", "image":"泽上有地，临。君子以教思无穷，容保民无疆。",
         "lines":["咸临，贞吉。","咸临，吉无不利。","甘临，无攸利。既忧之，无咎。","至临，无咎。","知临，大君之宜，吉。","敦临，吉无咎。"]},
    20: {"name":"风地观",  "symbol":"䷓", "upper":"巽","lower":"坤",
         "judgment":"盥而不荐，有孚颙若。", "image":"风行地上，观。先王以省方，观民设教。",
         "lines":["童观，小人无咎，君子吝。","窥观，利女贞。","观我生，进退。","观国之光，利用宾于王。","观我生，君子无咎。","观其生，君子无咎。"]},
    21: {"name":"火雷噬嗑","symbol":"䷔", "upper":"离","lower":"震",
         "judgment":"亨，利用狱。", "image":"雷电噬嗑，先王以明罚敕法。",
         "lines":["屦校灭趾，无咎。","噬肤灭鼻，无咎。","噬腊肉，遇毒，小吝，无咎。","噬干胏，得金矢，利艰贞，吉。","噬干肉，得黄金，贞厉，无咎。","何校灭耳，凶。"]},
    22: {"name":"山火贲",  "symbol":"䷕", "upper":"艮","lower":"离",
         "judgment":"亨。小利有攸往。", "image":"山下有火，贲。君子以明庶政，无敢折狱。",
         "lines":["贲其趾，舍车而徒。","贲其须。","贲如濡如，永贞吉。","贲如皤如，白马翰如，匪寇婚媾。","贲于丘园，束帛戋戋，吝，终吉。","白贲，无咎。"]},
    23: {"name":"山地剥",  "symbol":"䷖", "upper":"艮","lower":"坤",
         "judgment":"不利有攸往。", "image":"山附于地，剥。上以厚下安宅。",
         "lines":["剥床以足，蔑贞凶。","剥床以辨，蔑贞凶。","剥之，无咎。","剥床以肤，凶。","贯鱼，以宫人宠，无不利。","硕果不食，君子得舆，小人剥庐。"]},
    24: {"name":"地雷复",  "symbol":"䷗", "upper":"坤","lower":"震",
         "judgment":"亨。出入无疾，朋来无咎。反复其道，七日来复，利有攸往。",
         "image":"雷在地中，复。先王以至日闭关，商旅不行，后不省方。",
         "lines":["不远复，无祗悔，元吉。","休复，吉。","频复，厉无咎。","中行独复。","敦复，无悔。","迷复，凶，有灾眚。用行师，终有大败，以其国君凶，至于十年不克征。"]},
    25: {"name":"天雷无妄","symbol":"䷘", "upper":"乾","lower":"震",
         "judgment":"元亨利贞。其匪正有眚，不利有攸往。", "image":"天下雷行，物与无妄。先王以茂对时，育万物。",
         "lines":["无妄，往吉。","不耕获，不菑畲，则利有攸往。","无妄之灾，或系之牛，行人之得，邑人之灾。","可贞，无咎。","无妄之疾，勿药有喜。","无妄，行有眚，无攸利。"]},
    26: {"name":"山天大畜","symbol":"䷙", "upper":"艮","lower":"乾",
         "judgment":"利贞，不家食吉，利涉大川。", "image":"天在山中，大畜。君子以多识前言往行，以畜其德。",
         "lines":["有厉，利已。","舆说辐。","良马逐，利艰贞。曰闲舆卫，利有攸往。","童牛之牿，元吉。","豮豕之牙，吉。","何天之衢，亨。"]},
    27: {"name":"山雷颐",  "symbol":"䷚", "upper":"艮","lower":"震",
         "judgment":"贞吉。观颐，自求口实。", "image":"山下有雷，颐。君子以慎言语，节饮食。",
         "lines":["舍尔灵龟，观我朵颐，凶。","颠颐，拂经，于丘颐，征凶。","拂颐，贞凶。十年勿用，无攸利。","颠颐，吉。虎视眈眈，其欲逐逐，无咎。","拂经，居贞吉，不可涉大川。","由颐，厉吉，利涉大川。"]},
    28: {"name":"泽风大过","symbol":"䷛", "upper":"兑","lower":"巽",
         "judgment":"栋桡，利有攸往，亨。", "image":"泽灭木，大过。君子以独立不惧，遁世无闷。",
         "lines":["藉用白茅，无咎。","枯杨生稊，老夫得其女妻，无不利。","栋桡，凶。","栋隆，吉。有它吝。","枯杨生华，老妇得士夫，无咎无誉。","过涉灭顶，凶，无咎。"]},
    29: {"name":"坎为水",  "symbol":"䷜", "upper":"坎","lower":"坎",
         "judgment":"习坎，有孚，维心亨，行有尚。", "image":"水洊至，习坎。君子以常德行，习教事。",
         "lines":["习坎，入于坎窞，凶。","坎有险，求小得。","来之坎坎，险且枕，入于坎窞，勿用。","樽酒簋贰，用缶，纳约自牖，终无咎。","坎不盈，祗既平，无咎。","系用徽纆，寘于丛棘，三岁不得，凶。"]},
    30: {"name":"离为火",  "symbol":"䷝", "upper":"离","lower":"离",
         "judgment":"利贞，亨。畜牝牛，吉。", "image":"明两作，离。大人以继明照于四方。",
         "lines":["履错然，敬之无咎。","黄离，元吉。","日昃之离，不鼓缶而歌，则大耋之嗟，凶。","突如其来如，焚如，死如，弃如。","出涕沱若，戚嗟若，吉。","王用出征，有嘉折首，获匪其丑，无咎。"]},
    31: {"name":"泽山咸",  "symbol":"䷞", "upper":"兑","lower":"艮",
         "judgment":"亨利贞，取女吉。", "image":"山上有泽，咸。君子以虚受人。",
         "lines":["咸其拇。","咸其腓，凶，居吉。","咸其股，执其随，往吝。","贞吉悔亡，憧憧往来，朋从尔思。","咸其脢，无悔。","咸其辅颊舌。"]},
    32: {"name":"雷风恒",  "symbol":"䷟", "upper":"震","lower":"巽",
         "judgment":"亨，无咎，利贞，利有攸往。", "image":"雷风，恒。君子以立不易方。",
         "lines":["浚恒，贞凶，无攸利。","悔亡。","不恒其德，或承之羞，贞吝。","田无禽。","恒其德，贞，妇人吉，夫子凶。","振恒，凶。"]},
    33: {"name":"天山遁",  "symbol":"䷠", "upper":"乾","lower":"艮",
         "judgment":"亨，小利贞。", "image":"天下有山，遁。君子以远小人，不恶而严。",
         "lines":["遁尾，厉，勿用有攸往。","执之用黄牛之革，莫之胜说。","系遁，有疾厉，畜臣妾吉。","好遁，君子吉，小人否。","嘉遁，贞吉。","肥遁，无不利。"]},
    34: {"name":"雷天大壮","symbol":"䷡", "upper":"震","lower":"乾",
         "judgment":"利贞。", "image":"雷在天上，大壮。君子以非礼弗履。",
         "lines":["壮于趾，征凶，有孚。","贞吉。","小人用壮，君子用罔，贞厉。羝羊触藩，羸其角。","贞吉悔亡，藩决不羸，壮于大舆之輹。","丧羊于易，无悔。","羝羊触藩，不能退，不能遂，无攸利，艰则吉。"]},
    35: {"name":"火地晋",  "symbol":"䷢", "upper":"离","lower":"坤",
         "judgment":"康侯用锡马蕃庶，昼日三接。", "image":"明出地上，晋。君子以自昭明德。",
         "lines":["晋如摧如，贞吉。罔孚，裕无咎。","晋如愁如，贞吉。受兹介福，于其王母。","众允，悔亡。","晋如鼫鼠，贞厉。","悔亡，失得勿恤，往吉无不利。","晋其角，维用伐邑，厉吉无咎，贞吝。"]},
    36: {"name":"地火明夷","symbol":"䷣", "upper":"坤","lower":"离",
         "judgment":"利艰贞。", "image":"明入地中，明夷。君子以莅众，用晦而明。",
         "lines":["明夷于飞，垂其翼。君子于行，三日不食，有攸往，主人有言。","明夷，夷于左股，用拯马壮，吉。","明夷于南狩，得其大首，不可疾贞。","入于左腹，获明夷之心，于出门庭。","箕子之明夷，利贞。","不明晦，初登于天，后入于地。"]},
    37: {"name":"风火家人","symbol":"䷤", "upper":"巽","lower":"离",
         "judgment":"利女贞。", "image":"风自火出，家人。君子以言有物，而行有恒。",
         "lines":["闲有家，悔亡。","无攸遂，在中馈，贞吉。","家人嗃嗃，悔厉吉。妇子嘻嘻，终吝。","富家，大吉。","王假有家，勿恤吉。","有孚威如，终吉。"]},
    38: {"name":"火泽睽",  "symbol":"䷥", "upper":"离","lower":"兑",
         "judgment":"小事吉。", "image":"上火下泽，睽。君子以同而异。",
         "lines":["悔亡，丧马勿逐，自复。见恶人无咎。","遇主于巷，无咎。","见舆曳，其牛掣，其人天且劓，无初有终。","睽孤，遇元夫，交孚，厉无咎。","悔亡，厥宗噬肤，往何咎。","睽孤，见豕负涂，载鬼一车，先张之弧，后说之弧，匪寇婚媾，往遇雨则吉。"]},
    39: {"name":"水山蹇",  "symbol":"䷦", "upper":"坎","lower":"艮",
         "judgment":"利西南，不利东北。利见大人，贞吉。", "image":"山上有水，蹇。君子以反身修德。",
         "lines":["往蹇，来誉。","王臣蹇蹇，匪躬之故。","往蹇来反。","往蹇来连。","大蹇朋来。","往蹇来硕，吉。利见大人。"]},
    40: {"name":"雷水解",  "symbol":"䷧", "upper":"震","lower":"坎",
         "judgment":"利西南，无所往，其来复吉。有攸往，夙吉。", "image":"雷雨作，解。君子以赦过宥罪。",
         "lines":["无咎。","田获三狐，得黄矢，贞吉。","负且乘，致寇至，贞吝。","解而拇，朋至斯孚。","君子维有解，吉。有孚于小人。","公用射隼于高墉之上，获之，无不利。"]},
    41: {"name":"山泽损",  "symbol":"䷨", "upper":"艮","lower":"兑",
         "judgment":"有孚，元吉，无咎，可贞，利有攸往。曷之用，二簋可用享。",
         "image":"山下有泽，损。君子以惩忿窒欲。",
         "lines":["已事遄往，无咎，酌损之。","利贞，征凶，弗损益之。","三人行，则损一人。一人行，则得其友。","损其疾，使遄有喜，无咎。","或益之十朋之龟，弗克违，元吉。","弗损益之，无咎，贞吉，利有攸往，得臣无家。"]},
    42: {"name":"风雷益",  "symbol":"䷩", "upper":"巽","lower":"震",
         "judgment":"利有攸往，利涉大川。", "image":"风雷，益。君子以见善则迁，有过则改。",
         "lines":["利用为大作，元吉，无咎。","或益之十朋之龟，弗克违，永贞吉。王用享于帝，吉。","益之用凶事，无咎。有孚中行，告公用圭。","中行，告公从。利用为依迁国。","有孚惠心，勿问元吉。有孚惠我德。","莫益之，或击之，立心勿恒，凶。"]},
    43: {"name":"泽天夬",  "symbol":"䷪", "upper":"兑","lower":"乾",
         "judgment":"扬于王庭，孚号有厉。告自邑，不利即戎，利有攸往。",
         "image":"泽上于天，夬。君子以施禄及下，居德则忌。",
         "lines":["壮于前趾，往不胜为咎。","惕号，莫夜有戎，勿恤。","壮于頄，有凶。君子夬夬，独行遇雨，若濡有愠，无咎。","臀无肤，其行次且。牵羊悔亡，闻言不信。","苋陆夬夬，中行无咎。","无号，终有凶。"]},
    44: {"name":"天风姤",  "symbol":"䷫", "upper":"乾","lower":"巽",
         "judgment":"女壮，勿用取女。", "image":"天下有风，姤。后以施命诰四方。",
         "lines":["系于金柅，贞吉，有攸往，见凶，羸豕孚蹢躅。","包有鱼，无咎，不利宾。","臀无肤，其行次且，厉，无大咎。","包无鱼，起凶。","以杞包瓜，含章，有陨自天。","姤其角，吝，无咎。"]},
    45: {"name":"泽地萃",  "symbol":"䷬", "upper":"兑","lower":"坤",
         "judgment":"亨。王假有庙，利见大人，亨，利贞。用大牲吉，利有攸往。",
         "image":"泽上于地，萃。君子以除戎器，戒不虞。",
         "lines":["有孚不终，乃乱乃萃，若号一握为笑，勿恤，往无咎。","引吉，无咎，孚乃利用禴。","萃如嗟如，无攸利，往无咎，小吝。","大吉，无咎。","萃有位，无咎。匪孚，元永贞，悔亡。","赍咨涕洟，无咎。"]},
    46: {"name":"地风升",  "symbol":"䷭", "upper":"坤","lower":"巽",
         "judgment":"元亨，用见大人，勿恤，南征吉。", "image":"地中生木，升。君子以顺德，积小以高大。",
         "lines":["允升，大吉。","孚乃利用禴，无咎。","升虚邑。","王用亨于岐山，吉无咎。","贞吉，升阶。","冥升，利于不息之贞。"]},
    47: {"name":"泽水困",  "symbol":"䷮", "upper":"兑","lower":"坎",
         "judgment":"亨，贞，大人吉，无咎，有言不信。", "image":"泽无水，困。君子以致命遂志。",
         "lines":["臀困于株木，入于幽谷，三岁不觌。","困于酒食，朱绂方来，利用享祀，征凶，无咎。","困于石，据于蒺藜，入于其宫，不见其妻，凶。","来徐徐，困于金车，吝，有终。","劓刖，困于赤绂，乃徐有说，利用祭祀。","困于葛藟，于臲兀，曰动悔。有悔，征吉。"]},
    48: {"name":"水风井",  "symbol":"䷯", "upper":"坎","lower":"巽",
         "judgment":"改邑不改井，无丧无得，往来井井。汔至，亦未繘井，羸其瓶，凶。",
         "image":"木上有水，井。君子以劳民劝相。",
         "lines":["井泥不食，旧井无禽。","井谷射鲋，瓮敝漏。","井渫不食，为我心恻，可用汲，王明，并受其福。","井甃，无咎。","井洌，寒泉食。","井收勿幕，有孚元吉。"]},
    49: {"name":"泽火革",  "symbol":"䷰", "upper":"兑","lower":"离",
         "judgment":"己日乃孚，元亨利贞，悔亡。", "image":"泽中有火，革。君子以治历明时。",
         "lines":["巩用黄牛之革。","己日乃革之，征吉，无咎。","征凶，贞厉，革言三就，有孚。","悔亡，有孚改命，吉。","大人虎变，未占有孚。","君子豹变，小人革面，征凶，居贞吉。"]},
    50: {"name":"火风鼎",  "symbol":"䷱", "upper":"离","lower":"巽",
         "judgment":"元吉，亨。", "image":"木上有火，鼎。君子以正位凝命。",
         "lines":["鼎颠趾，利出否，得妾以其子，无咎。","鼎有实，我仇有疾，不我能即，吉。","鼎耳革，其行塞，雉膏不食，方雨亏悔，终吉。","鼎折足，覆公餗，其形渥，凶。","鼎黄耳金铉，利贞。","鼎玉铉，大吉，无不利。"]},
    51: {"name":"震为雷",  "symbol":"䷲", "upper":"震","lower":"震",
         "judgment":"亨。震来虩虩，笑言哑哑。震惊百里，不丧匕鬯。",
         "image":"洊雷，震。君子以恐惧修省。",
         "lines":["震来虩虩，后笑言哑哑，吉。","震来厉，亿丧贝，跻于九陵，勿逐，七日得。","震苏苏，震行无眚。","震遂泥。","震往来厉，亿无丧，有事。","震索索，视矍矍，征凶。震不于其躬，于其邻，无咎。婚媾有言。"]},
    52: {"name":"艮为山",  "symbol":"䷳", "upper":"艮","lower":"艮",
         "judgment":"艮其背，不获其身，行其庭，不见其人，无咎。",
         "image":"兼山，艮。君子以思不出其位。",
         "lines":["艮其趾，无咎，利永贞。","艮其腓，不拯其随，其心不快。","艮其限，列其夤，厉薰心。","艮其身，无咎。","艮其辅，言有序，悔亡。","敦艮，吉。"]},
    53: {"name":"风山渐",  "symbol":"䷴", "upper":"巽","lower":"艮",
         "judgment":"女归吉，利贞。", "image":"山上有木，渐。君子以居贤德善俗。",
         "lines":["鸿渐于干，小子厉，有言，无咎。","鸿渐于磐，饮食衎衎，吉。","鸿渐于陆，夫征不复，妇孕不育，凶。利御寇。","鸿渐于木，或得其桷，无咎。","鸿渐于陵，妇三岁不孕，终莫之胜，吉。","鸿渐于逵，其羽可用为仪，吉。"]},
    54: {"name":"雷泽归妹","symbol":"䷵", "upper":"震","lower":"兑",
         "judgment":"征凶，无攸利。", "image":"泽上有雷，归妹。君子以永终知敝。",
         "lines":["归妹以娣，跛能履，征吉。","眇能视，利幽人之贞。","归妹以须，反归以娣。","归妹愆期，迟归有时。","帝乙归妹，其君之袂，不如其娣之袂良，月几望，吉。","女承筐无实，士刲羊无血，无攸利。"]},
    55: {"name":"雷火丰",  "symbol":"䷶", "upper":"震","lower":"离",
         "judgment":"亨，王假之，勿忧，宜日中。", "image":"雷电皆至，丰。君子以折狱致刑。",
         "lines":["遇其配主，虽旬无咎，往有尚。","丰其蔀，日中见斗，往得疑疾，有孚发若，吉。","丰其沛，日中见沫，折其右肱，无咎。","丰其蔀，日中见斗，遇其夷主，吉。","来章，有庆誉，吉。","丰其屋，蔀其家，窥其户，阒其无人，三岁不觌，凶。"]},
    56: {"name":"火山旅",  "symbol":"䷷", "upper":"离","lower":"艮",
         "judgment":"小亨，旅贞吉。", "image":"山上有火，旅。君子以明慎用刑，而不留狱。",
         "lines":["旅琐琐，斯其所取灾。","旅即次，怀其资，得童仆贞。","旅焚其次，丧其童仆，贞厉。","旅于处，得其资斧，我心不快。","射雉一矢亡，终以誉命。","鸟焚其巢，旅人先笑后号咷。丧牛于易，凶。"]},
    57: {"name":"巽为风",  "symbol":"䷸", "upper":"巽","lower":"巽",
         "judgment":"小亨，利有攸往，利见大人。", "image":"随风，巽。君子以申命行事。",
         "lines":["进退，利武人之贞。","巽在床下，用史巫纷若，吉无咎。","频巽，吝。","悔亡，田获三品。","贞吉悔亡，无不利。无初有终，先庚三日，后庚三日，吉。","巽在床下，丧其资斧，贞凶。"]},
    58: {"name":"兑为泽",  "symbol":"䷹", "upper":"兑","lower":"兑",
         "judgment":"亨利贞。", "image":"丽泽，兑。君子以朋友讲习。",
         "lines":["和兑，吉。","孚兑，吉，悔亡。","来兑，凶。","商兑，未宁，介疾有喜。","孚于剥，有厉。","引兑。"]},
    59: {"name":"风水涣",  "symbol":"䷺", "upper":"巽","lower":"坎",
         "judgment":"亨。王假有庙，利涉大川，利贞。", "image":"风行水上，涣。先王以享于帝立庙。",
         "lines":["用拯马壮，吉。","涣奔其机，悔亡。","涣其躬，无悔。","涣其群，元吉。涣有丘，匪夷所思。","涣汗其大号，涣王居，无咎。","涣其血，去逖出，无咎。"]},
    60: {"name":"水泽节",  "symbol":"䷻", "upper":"坎","lower":"兑",
         "judgment":"亨。苦节不可贞。", "image":"泽上有水，节。君子以制数度，议德行。",
         "lines":["不出户庭，无咎。","不出门庭，凶。","不节若，则嗟若，无咎。","安节，亨。","甘节，吉。往有尚。","苦节，贞凶，悔亡。"]},
    61: {"name":"风泽中孚","symbol":"䷼", "upper":"巽","lower":"兑",
         "judgment":"豚鱼吉，利涉大川，利贞。", "image":"泽上有风，中孚。君子以议狱缓死。",
         "lines":["虞吉，有他不燕。","鸣鹤在阴，其子和之，我有好爵，吾与尔靡之。","得敌，或鼓或罢，或泣或歌。","月几望，马匹亡，无咎。","有孚挛如，无咎。","翰音登于天，贞凶。"]},
    62: {"name":"雷山小过","symbol":"䷽", "upper":"震","lower":"艮",
         "judgment":"亨利贞，可小事，不可大事。飞鸟遗之音，不宜上宜下，大吉。",
         "image":"山上有雷，小过。君子以行过乎恭，丧过乎哀，用过乎俭。",
         "lines":["飞鸟以凶。","过其祖，遇其妣。不及其君，遇其臣。无咎。","弗过防之，从或戕之，凶。","无咎，弗过遇之。往厉必戒，勿用永贞。","密云不雨，自我西郊，公弋取彼在穴。","弗遇过之，飞鸟离之，凶，是谓灾眚。"]},
    63: {"name":"水火既济","symbol":"䷾", "upper":"坎","lower":"离",
         "judgment":"亨小，利贞，初吉终乱。", "image":"水在火上，既济。君子以思患而预防之。",
         "lines":["曳其轮，濡其尾，无咎。","妇丧其茀，勿逐，七日得。","高宗伐鬼方，三年克之，小人勿用。","繻有衣袽，终日戒。","东邻杀牛，不如西邻之禴祭，实受其福。","濡其首，厉。"]},
    64: {"name":"火水未济","symbol":"䷿", "upper":"离","lower":"坎",
         "judgment":"亨，小狐汔济，濡其尾，无攸利。", "image":"火在水上，未济。君子以慎辨物居方。",
         "lines":["濡其尾，吝。","曳其轮，贞吉。","未济，征凶，利涉大川。","贞吉悔亡，震用伐鬼方，三年有赏于大国。","贞吉无悔，君子之光，有孚吉。","有孚于饮酒，无咎，濡其首，有孚失是。"]},
}

# 八卦映射
TRIGRAMS = {
    "乾": {"binary":"111","element":"天","direction":"西北","nature":"健"},
    "兑": {"binary":"110","element":"泽","direction":"西","nature":"悦"},
    "离": {"binary":"101","element":"火","direction":"南","nature":"丽"},
    "震": {"binary":"100","element":"雷","direction":"东","nature":"动"},
    "巽": {"binary":"011","element":"风","direction":"东南","nature":"入"},
    "坎": {"binary":"010","element":"水","direction":"北","nature":"陷"},
    "艮": {"binary":"001","element":"山","direction":"东北","nature":"止"},
    "坤": {"binary":"000","element":"地","direction":"西南","nature":"顺"},
}

# 上卦+下卦 → 卦序号
HEXAGRAM_INDEX = {}
for num, h in HEXAGRAMS.items():
    key = f"{h['upper']}+{h['lower']}"
    HEXAGRAM_INDEX[key] = num

# ==================== 六爻起卦算法 ====================
def cast_coins() -> tuple:
    """三枚铜钱摇一次，返回 (line_value, is_changing)
    6=老阴(变), 7=少阳(不变), 8=少阴(不变), 9=老阳(变)
    """
    coins = [random.randint(0, 1) for _ in range(3)]  # 0=字(阴2), 1=背(阳3)
    total = sum(c + 2 for c in coins)  # 6~9
    line = 1 if total in (7, 9) else 0  # 阳=1, 阴=0
    changing = total in (6, 9)
    return line, changing, total

def get_hexagram_from_lines(lines: list) -> int:
    """从6条爻线获取卦序号（从下往上）"""
    upper_lines = ''.join(str(l) for l in reversed(lines[3:6]))  # 上卦(4,5,6爻)
    lower_lines = ''.join(str(l) for l in reversed(lines[0:3]))  # 下卦(1,2,3爻)
    trigram_map = {v["binary"]: k for k, v in TRIGRAMS.items()}
    upper = trigram_map.get(upper_lines, "坤")
    lower = trigram_map.get(lower_lines, "坤")
    return HEXAGRAM_INDEX.get(f"{upper}+{lower}", 2)

def get_hugua(origin_lines: list) -> int:
    """计算互卦（2,3,4爻为下卦，3,4,5爻为上卦）"""
    lower = ''.join(str(origin_lines[i]) for i in [2, 1, 0])  # 2,3,4爻
    upper = ''.join(str(origin_lines[i]) for i in [4, 3, 2])  # 3,4,5爻
    trigram_map = {v["binary"]: k for k, v in TRIGRAMS.items()}
    u = trigram_map.get(upper, "坤")
    l = trigram_map.get(lower, "坤")
    return HEXAGRAM_INDEX.get(f"{u}+{l}", 2)

# ==================== 用户工具 ====================
def get_or_create_user(db, user_id: str) -> dict:
    db.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
    # 初始化武器
    for wid in ["express-knife","rusty-cleaver"]:
        db.execute("INSERT OR IGNORE INTO weapons (user_id, weapon_id, unlocked) VALUES (?,?,1)", (user_id, wid))
    return dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

def get_daily_count(db, user_id: str) -> int:
    today = datetime.date.today().isoformat()
    row = db.execute("SELECT divination_count FROM daily_stats WHERE user_id=? AND date=?", (user_id, today)).fetchone()
    return row["divination_count"] if row else 0

def get_weapon_data(db, user_id: str) -> dict:
    rows = db.execute("SELECT * FROM weapons WHERE user_id=?", (user_id,)).fetchall()
    return {r["weapon_id"]: {"level": r["level"], "unlocked": bool(r["unlocked"])} for r in rows}

# ==================== API 模型 ====================
class DivinationRequest(BaseModel):
    user_id: str
    weapon_id: str
    question: str = ""

class UserInitRequest(BaseModel):
    user_id: str
    nickname: Optional[str] = None

class SignInRequest(BaseModel):
    user_id: str

class UpgradeWeaponRequest(BaseModel):
    user_id: str
    weapon_id: str

# ==================== API 路由 ====================
@app.on_event("startup")
async def startup():
    init_db()

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0"}

@app.post("/api/user/init")
async def init_user(req: UserInitRequest):
    with get_db() as db:
        user = get_or_create_user(db, req.user_id)
        if req.nickname:
            db.execute("UPDATE users SET nickname=? WHERE id=?", (req.nickname, req.user_id))
        weapons = get_weapon_data(db, req.user_id)
        return {
            "user": dict(db.execute("SELECT * FROM users WHERE id=?", (req.user_id,)).fetchone()),
            "weapons": weapons,
            "daily_count": get_daily_count(db, req.user_id),
            "daily_limit": 3
        }

@app.post("/api/divination")
async def do_divination(req: DivinationRequest):
    """
    核心起卦逻辑：
    1. 三枚铜钱摇六次
    2. 生成本卦、变卦、互卦
    3. 调用 AI 解读（如有 API Key）
    4. 扣减灵力/次数
    """
    with get_db() as db:
        user = get_or_create_user(db, req.user_id)
        daily_count = get_daily_count(db, req.user_id)
        user_spirit = user["spirit"]
        daily_limit = 3

        # 每日前3次免费，之后扣1灵力
        if daily_count >= daily_limit:
            if user_spirit < 1:
                raise HTTPException(400, "灵力不足！请明日签到获取灵力后再来破阵。")
            db.execute("UPDATE users SET spirit = spirit - 1 WHERE id=?", (req.user_id,))
        else:
            # 更新每日计数
            today = datetime.date.today().isoformat()
            db.execute("INSERT OR REPLACE INTO daily_stats (user_id, date, divination_count) VALUES (?,?,?)",
                       (req.user_id, today, daily_count + 1))

        # 起卦
        lines = []
        changing_indices = []
        coin_results = []
        for i in range(6):
            line, changing, total = cast_coins()
            lines.append(line)
            coin_results.append(total)
            if changing:
                changing_indices.append(i + 1)  # 1-based

        origin_hex = get_hexagram_from_lines(lines)

        # 变卦
        changed_lines = lines.copy()
        for idx in changing_indices:
            changed_lines[idx - 1] = 1 - changed_lines[idx - 1]  # 翻转
        changed_hex = get_hexagram_from_lines(changed_lines) if changing_indices else 0

        # 互卦
        hugua_hex = get_hugua(lines)

        # 构建卦象详情
        origin_data = HEXAGRAMS[origin_hex]
        changing_detail = []
        for idx in changing_indices:
            changing_detail.append({
                "position": idx,
                "name": ["初","二","三","四","五","上"][idx-1],
                "line_text": origin_data["lines"][idx-1],
                "from": "老阳" if lines[idx-1] == 1 else "老阴",
                "to": "少阴" if lines[idx-1] == 1 else "少阳"
            })

        # AI 解读
        ai_judgment = None
        if DEEPSEEK_API_KEY and req.question:
            hugua_data = {
                "id": hugua_hex,
                "name": HEXAGRAMS[hugua_hex]["name"],
                "symbol": HEXAGRAMS[hugua_hex]["symbol"],
            }
            ai_judgment = await ai_interpret(req.question, origin_data, changing_detail, origin_hex, changed_hex, hugua_data)

        # 保存记录
        db.execute("""
            INSERT INTO divinations (user_id, weapon_id, question, hexagram_origin, hexagram_changed, changing_lines, judgment)
            VALUES (?,?,?,?,?,?,?)
        """, (req.user_id, req.weapon_id, req.question, origin_hex, changed_hex,
              ",".join(map(str, changing_indices)), ai_judgment))

        # 增加经验
        db.execute("UPDATE users SET exp = exp + 10 WHERE id=?", (req.user_id,))
        # 检查升级
        user_after = dict(db.execute("SELECT * FROM users WHERE id=?", (req.user_id,)).fetchone())
        new_level = user_after["exp"] // 100 + 1
        if new_level > user_after["level"]:
            db.execute("UPDATE users SET level = ? WHERE id=?", (new_level, req.user_id))

        # 检查兵器解锁
        total_divs = db.execute("SELECT COUNT(*) as cnt FROM divinations WHERE user_id=?", (req.user_id,)).fetchone()["cnt"]
        new_unlocks = []
        for wid, cond in WEAPON_UNLOCK.items():
            existing = db.execute("SELECT unlocked FROM weapons WHERE user_id=? AND weapon_id=?", (req.user_id, wid)).fetchone()
            if not existing:
                db.execute("INSERT INTO weapons (user_id, weapon_id, unlocked) VALUES (?,?,0)", (req.user_id, wid))
                existing = {"unlocked": 0}
            if not existing["unlocked"]:
                if new_level >= cond["level"] or total_divs >= cond["divinations"]:
                    db.execute("UPDATE weapons SET unlocked=1 WHERE user_id=? AND weapon_id=?", (req.user_id, wid))
                    new_unlocks.append({"weapon_id": wid, "name": cond["name"]})

        # 更新每日任务进度
        today = datetime.date.today().isoformat()
        task_updates = update_daily_tasks(db, req.user_id, today, req.weapon_id)

        return {
            "success": True,
            "hexagram_origin": {
                "id": origin_hex,
                "name": origin_data["name"],
                "symbol": origin_data["symbol"],
                "upper": origin_data["upper"],
                "lower": origin_data["lower"],
                "judgment": origin_data["judgment"],
                "image": origin_data["image"],
            },
            "hexagram_changed": {
                "id": changed_hex,
                "name": HEXAGRAMS[changed_hex]["name"],
                "symbol": HEXAGRAMS[changed_hex]["symbol"],
                "judgment": HEXAGRAMS[changed_hex]["judgment"],
            } if changed_hex else None,
            "hexagram_hugua": {
                "id": hugua_hex,
                "name": HEXAGRAMS[hugua_hex]["name"],
                "symbol": HEXAGRAMS[hugua_hex]["symbol"],
            },
            "changing_lines": changing_detail,
            "coin_results": coin_results,
            "ai_judgment": ai_judgment,
            "spirit_remaining": dict(db.execute("SELECT spirit FROM users WHERE id=?", (req.user_id,)).fetchone())["spirit"],
            "daily_count": daily_count + 1 if daily_count < daily_limit else daily_count,
            "daily_limit": daily_limit,
            "level_up": new_level > user["level"],
            "new_level": new_level if new_level > user["level"] else None,
            "new_unlocks": new_unlocks,
            "task_updates": task_updates,
        }

@app.post("/api/signin")
async def sign_in(req: SignInRequest):
    with get_db() as db:
        user = get_or_create_user(db, req.user_id)
        today = datetime.date.today().isoformat()
        last = user["signin_date"]
        streak = user["signin_streak"]

        if last == today:
            return {"success": False, "message": "今日已签到", "spirit": user["spirit"], "streak": streak}

        # 连续签到判定
        if last:
            last_date = datetime.date.fromisoformat(last)
            if (datetime.date.today() - last_date).days == 1:
                streak += 1
            else:
                streak = 1
        else:
            streak = 1

        # 奖励灵力：基础3 + 连续签到加成
        bonus = min(streak - 1, 7)  # 最多+7
        spirit_gain = 3 + bonus

        db.execute("UPDATE users SET signin_date=?, signin_streak=?, spirit=spirit+? WHERE id=?",
                   (today, streak, spirit_gain, req.user_id))

        return {
            "success": True,
            "spirit_gain": spirit_gain,
            "streak": streak,
            "spirit_total": user["spirit"] + spirit_gain,
        }

@app.post("/api/weapon/upgrade")
async def upgrade_weapon(req: UpgradeWeaponRequest):
    with get_db() as db:
        w = db.execute("SELECT * FROM weapons WHERE user_id=? AND weapon_id=? AND unlocked=1",
                       (req.user_id, req.weapon_id)).fetchone()
        if not w:
            raise HTTPException(400, "兵器未解锁")

        user = dict(db.execute("SELECT * FROM users WHERE id=?", (req.user_id,)).fetchone())
        cost = w["level"] * 5  # 灵力消耗随等级增长
        if user["spirit"] < cost:
            raise HTTPException(400, f"灵力不足！需要 {cost} 灵力，当前 {user['spirit']}")

        new_level = w["level"] + 1
        db.execute("UPDATE weapons SET level=? WHERE user_id=? AND weapon_id=?", (new_level, req.user_id, req.weapon_id))
        db.execute("UPDATE users SET spirit = spirit - ? WHERE id=?", (cost, req.user_id))

        return {
            "success": True,
            "weapon_id": req.weapon_id,
            "new_level": new_level,
            "cost": cost,
            "spirit_remaining": user["spirit"] - cost,
        }

@app.get("/api/history/{user_id}")
async def get_history(user_id: str, limit: int = Query(10, ge=1, le=50)):
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM divinations WHERE user_id=? ORDER BY created_at DESC LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    with get_db() as db:
        user = get_or_create_user(db, user_id)
        weapons = get_weapon_data(db, user_id)
        history_count = db.execute("SELECT COUNT(*) as cnt FROM divinations WHERE user_id=?", (user_id,)).fetchone()["cnt"]
        return {
            "user": dict(user),
            "weapons": weapons,
            "daily_count": get_daily_count(db, user_id),
            "daily_limit": 3,
            "total_divinations": history_count,
        }

@app.get("/api/achievements/{user_id}")
async def get_achievements(user_id: str):
    with get_db() as db:
        get_or_create_user(db, user_id)
        # 检查并解锁成就
        check_achievements(db, user_id)
        rows = db.execute("SELECT * FROM achievements WHERE user_id=?", (user_id,)).fetchall()
        return [dict(r) for r in rows]

# ==================== AI 解卦（DeepSeek） ====================
async def ai_interpret(question: str, origin: dict, changing: list, origin_id: int, changed_id: int, hugua: dict = None) -> str:
    if not DEEPSEEK_API_KEY:
        return None

    changing_text = ""
    if changing:
        changing_text = "动爻：\n" + "\n".join(
            f"  {c['name']}爻：{c['line_text']}（{c['from']}→{c['to']}）" for c in changing
        )

    hugua_text = ""
    if hugua:
        hugua_text = f"\n互卦：{hugua['name']}（{hugua['symbol']}）"

    prompt = f"""你是一位精通《易经》的资深卦师，擅长用清晰、实用的语言为用户解卦。

用户问：{question}

卦象信息：
本卦：第{origin_id}卦 {origin['name']}（{origin['symbol']}）
上卦{origin['upper']}下卦{origin['lower']}
卦辞：{origin['judgment']}
大象：{origin['image']}
{changing_text}
{"变卦：第"+str(changed_id)+"卦 "+HEXAGRAMS[changed_id]['name']+"（"+HEXAGRAMS[changed_id]['symbol']+"）" if changed_id else "本卦无动爻，静卦"}
{hugua_text}

请按照以下结构详细解读（语言通俗易懂，要有实际指导意义）：

一、本卦详解：解释卦名含义、卦辞释义、大象寓意，以及静卦/动卦的影响
二、互卦分析（如有）：说明互卦代表的事情发展中段过程和内在因素
三、针对「{question}」析趋势：给出趋势分析，分点说明哪些情况有利、哪些需要注意
四、行动提点：给出具体的行动建议和注意事项

使用✅和⚠️符号突出重点，让用户一目了然。"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "你是一位传统文化研究者，精通六十四卦，善于用古雅而通俗的语言进行文化科普。请按照结构：一、本卦详解；二、互卦分析；三、针对问题析趋势；四、行动提点。详细解答用户的问题。内容仅供游戏娱乐和传统文化科普。"},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.7,
                }
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI 解卦失败: {e}")
        return None

# ==================== 兵器解锁条件 ====================
WEAPON_UNLOCK = {
    "iron-sword":    {"level": 3, "divinations": 5,  "name": "精铁长剑", "hint": "道行3级 或 破阵5次"},
    "willow-dagger": {"level": 5, "divinations": 10, "name": "柳叶飞刀", "hint": "道行5级 或 破阵10次"},
    "dragon-blade":  {"level": 8, "divinations": 30, "name": "屠龙刀",   "hint": "道行8级 或 破阵30次"},
    "heaven-sword":  {"level": 10, "divinations": 50, "name": "倚天剑",   "hint": "道行10级 或 破阵50次"},
}

# ==================== 每日任务 ====================
DAILY_TASKS = {
    "divine_1":    {"name": "问道一次", "desc": "完成1次起卦", "target": 1, "reward_spirit": 2, "reward_exp": 5},
    "divine_3":    {"name": "问道三次", "desc": "完成3次起卦", "target": 3, "reward_spirit": 5, "reward_exp": 10},
    "use_king":    {"name": "王者之兵", "desc": "使用王者兵器破阵1次", "target": 1, "reward_spirit": 3, "reward_exp": 15},
    "any_success": {"name": "破阵成功", "desc": "成功破阵1次", "target": 1, "reward_spirit": 2, "reward_exp": 8},
}

# ==================== 成就系统 ====================
ACHIEVEMENTS = {
    "first_break":    {"name":"初破阵法","desc":"首次成功破阵"},
    "ten_divinations": {"name":"问道十次","desc":"累计完成10次起卦"},
    "fifty_divinations":{"name":"半百问道","desc":"累计完成50次起卦"},
    "hundred_divinations":{"name":"百卦通玄","desc":"累计完成100次起卦"},
    "all_bronze":     {"name":"凡铁宗师","desc":"解锁全部青铜兵器"},
    "all_silver":     {"name":"银刃名家","desc":"解锁全部白银兵器"},
    "all_king":       {"name":"王者之兵","desc":"解锁全部王者兵器"},
    "streak_7":       {"name":"七日问道","desc":"连续签到7天"},
    "level_5":        {"name":"初窥门径","desc":"道行达到5级"},
    "level_10":       {"name":"登堂入室","desc":"道行达到10级"},
}

# ==================== 今日状态 ====================
FORTUNE_LEVELS = ["大吉", "吉", "小吉", "平", "小凶", "凶"]
FORTUNE_ADVICE = {
    "大吉": "状态极佳，诸事顺遂，适合积极探索。",
    "吉":   "状态不错，宜积极进取，把握机会。",
    "小吉": "略有波折但总体向好，谨慎行事即可。",
    "平":   "状态平稳，不宜冒进，稳扎稳打。",
    "小凶": "状态一般，宜静不宜动，避免冲动行事。",
    "凶":   "状态欠佳，宜守不宜攻，保持冷静。",
}

def update_daily_tasks(db, user_id: str, date: str, weapon_id: str) -> list:
    """更新每日任务进度，返回有进展的任务列表"""
    updates = []
    # 确保任务记录存在
    for tid in DAILY_TASKS:
        db.execute("INSERT OR IGNORE INTO daily_tasks (user_id, date, task_id, target) VALUES (?,?,?,?)",
                   (user_id, date, tid, DAILY_TASKS[tid]["target"]))

    # 起卦计数任务
    for tid in ["divine_1", "divine_3"]:
        row = db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=? AND task_id=?",
                         (user_id, date, tid)).fetchone()
        if row["progress"] < row["target"] and not row["claimed"]:
            db.execute("UPDATE daily_tasks SET progress = progress + 1 WHERE user_id=? AND date=? AND task_id=?",
                       (user_id, date, tid))
            new_prog = row["progress"] + 1
            updates.append({"task_id": tid, "progress": new_prog, "target": row["target"],
                          "name": DAILY_TASKS[tid]["name"], "completed": new_prog >= row["target"]})

    # 王者兵器任务
    if weapon_id in ("dragon-blade", "heaven-sword"):
        row = db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=? AND task_id='use_king'",
                         (user_id, date)).fetchone()
        if row["progress"] < row["target"] and not row["claimed"]:
            db.execute("UPDATE daily_tasks SET progress = progress + 1 WHERE user_id=? AND date=? AND task_id='use_king'",
                       (user_id, date))
            new_prog = row["progress"] + 1
            updates.append({"task_id": "use_king", "progress": new_prog, "target": row["target"],
                          "name": DAILY_TASKS["use_king"]["name"], "completed": True})

    # 破阵成功任务
    row = db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=? AND task_id='any_success'",
                     (user_id, date)).fetchone()
    if row["progress"] < row["target"] and not row["claimed"]:
        db.execute("UPDATE daily_tasks SET progress = progress + 1 WHERE user_id=? AND date=? AND task_id='any_success'",
                   (user_id, date))
        new_prog = row["progress"] + 1
        updates.append({"task_id": "any_success", "progress": new_prog, "target": row["target"],
                      "name": DAILY_TASKS["any_success"]["name"], "completed": True})

    return updates

def check_achievements(db, user_id: str):
    user = dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    total = db.execute("SELECT COUNT(*) as cnt FROM divinations WHERE user_id=?", (user_id,)).fetchone()["cnt"]
    existing = set(r["ach_id"] for r in db.execute("SELECT ach_id FROM achievements WHERE user_id=?", (user_id,)).fetchall())

    weapons = {r["weapon_id"]: r["unlocked"] for r in db.execute("SELECT weapon_id, unlocked FROM weapons WHERE user_id=?", (user_id,)).fetchall()}

    checks = {
        "first_break": total >= 1,
        "ten_divinations": total >= 10,
        "fifty_divinations": total >= 50,
        "hundred_divinations": total >= 100,
        "all_bronze": weapons.get("express-knife",0) and weapons.get("rusty-cleaver",0),
        "all_silver": weapons.get("iron-sword",0) and weapons.get("willow-dagger",0),
        "all_king": weapons.get("dragon-blade",0) and weapons.get("heaven-sword",0),
        "streak_7": user["signin_streak"] >= 7,
        "level_5": user["level"] >= 5,
        "level_10": user["level"] >= 10,
    }

    for ach_id, achieved in checks.items():
        if achieved and ach_id not in existing:
            db.execute("INSERT OR IGNORE INTO achievements (user_id, ach_id) VALUES (?,?)", (user_id, ach_id))

# ==================== 每日任务 API ====================
@app.get("/api/daily-tasks/{user_id}")
async def get_daily_tasks(user_id: str):
    with get_db() as db:
        get_or_create_user(db, user_id)
        today = datetime.date.today().isoformat()
        # 确保今天的任务记录存在
        for tid in DAILY_TASKS:
            db.execute("INSERT OR IGNORE INTO daily_tasks (user_id, date, task_id, target) VALUES (?,?,?,?)",
                       (user_id, today, tid, DAILY_TASKS[tid]["target"]))
        rows = db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=?", (user_id, today)).fetchall()
        tasks = []
        for r in rows:
            tdef = DAILY_TASKS.get(r["task_id"], {})
            tasks.append({
                "task_id": r["task_id"],
                "name": tdef.get("name", ""),
                "desc": tdef.get("desc", ""),
                "progress": r["progress"],
                "target": r["target"],
                "claimed": bool(r["claimed"]),
                "reward_spirit": tdef.get("reward_spirit", 0),
                "reward_exp": tdef.get("reward_exp", 0),
                "completed": r["progress"] >= r["target"] and not r["claimed"],
            })
        return tasks

@app.post("/api/daily-tasks/claim")
async def claim_task(req: dict):
    user_id = req.get("user_id")
    task_id = req.get("task_id")
    today = datetime.date.today().isoformat()
    with get_db() as db:
        row = db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=? AND task_id=?",
                         (user_id, today, task_id)).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        if row["claimed"]:
            raise HTTPException(400, "已领取")
        if row["progress"] < row["target"]:
            raise HTTPException(400, "任务未完成")
        tdef = DAILY_TASKS.get(task_id, {})
        db.execute("UPDATE daily_tasks SET claimed=1 WHERE user_id=? AND date=? AND task_id=?",
                   (user_id, today, task_id))
        db.execute("UPDATE users SET spirit=spirit+?, exp=exp+? WHERE id=?",
                   (tdef.get("reward_spirit", 0), tdef.get("reward_exp", 0), user_id))
        user = dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        return {
            "success": True,
            "reward_spirit": tdef.get("reward_spirit", 0),
            "reward_exp": tdef.get("reward_exp", 0),
            "spirit_total": user["spirit"],
            "exp_total": user["exp"],
        }

# ==================== 今日状态 API ====================
@app.get("/api/fortune/{user_id}")
async def get_fortune(user_id: str):
    with get_db() as db:
        get_or_create_user(db, user_id)
        today = datetime.date.today()
        # 基于日期+用户ID生成确定性运势（同一天同一用户运势不变）
        seed_str = f"{user_id}{today.isoformat()}"
        seed = sum(ord(c) for c in seed_str)
        random.seed(seed)
        # 签到加成：连续签到影响运势
        user = dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        streak = user.get("signin_streak", 0)
        # 基础运势
        base_idx = random.randint(0, 5)
        # 连续签到7天以上，运势提升一档
        if streak >= 7:
            base_idx = max(0, base_idx - 1)
        fortune = FORTUNE_LEVELS[base_idx]
        # 幸运方位
        directions = ["东", "南", "西", "北", "东南", "东北", "西南", "西北"]
        lucky_dir = random.choice(directions)
        # 幸运数字
        lucky_num = random.randint(1, 99)
        # 幸运色
        colors = ["赤", "黄", "青", "白", "黑", "金", "紫", "绿"]
        lucky_color = random.choice(colors)
        random.seed()
        return {
            "date": today.isoformat(),
            "fortune": fortune,
            "advice": FORTUNE_ADVICE.get(fortune, ""),
            "lucky_direction": lucky_dir,
            "lucky_number": lucky_num,
            "lucky_color": lucky_color,
            "signin_streak": streak,
        }

# ==================== 八卦知识库 API ====================
@app.get("/api/hexagram/{hex_id}")
async def get_hexagram_detail(hex_id: int):
    if hex_id not in HEXAGRAMS:
        raise HTTPException(404, "卦象不存在")
    h = HEXAGRAMS[hex_id]
    return {
        "id": hex_id,
        "name": h["name"],
        "symbol": h["symbol"],
        "upper": h["upper"],
        "lower": h["lower"],
        "judgment": h["judgment"],
        "image": h["image"],
        "lines": [{"position": ["初","二","三","四","五","上"][i], "text": h["lines"][i]} for i in range(6)],
        "trigram_upper": TRIGRAMS.get(h["upper"], {}),
        "trigram_lower": TRIGRAMS.get(h["lower"], {}),
    }

@app.get("/api/hexagrams")
async def list_hexagrams(search: str = ""):
    """搜索/列出卦象"""
    results = []
    for num, h in HEXAGRAMS.items():
        if not search or search in h["name"] or search in h["upper"] or search in h["lower"]:
            results.append({"id": num, "name": h["name"], "symbol": h["symbol"],
                          "upper": h["upper"], "lower": h["lower"], "judgment": h["judgment"][:20]})
    return results

# ==================== 兵器解锁状态 API ====================
@app.get("/api/weapon-unlock/{user_id}")
async def get_weapon_unlock_status(user_id: str):
    with get_db() as db:
        user = get_or_create_user(db, user_id)
        total = db.execute("SELECT COUNT(*) as cnt FROM divinations WHERE user_id=?", (user_id,)).fetchone()["cnt"]
        result = {}
        for wid, cond in WEAPON_UNLOCK.items():
            w = db.execute("SELECT unlocked FROM weapons WHERE user_id=? AND weapon_id=?", (user_id, wid)).fetchone()
            unlocked = bool(w["unlocked"]) if w else False
            result[wid] = {
                "unlocked": unlocked,
                "hint": cond["hint"],
                "req_level": cond["level"],
                "req_divs": cond["divinations"],
                "current_level": user["level"],
                "current_divs": total,
            }
        return result

# ==================== 启动 ====================
if __name__ == "__main__":
    import uvicorn
    print("兵器破阵 · 易经起卦 后端启动中...")
    print(f"   API 文档: http://localhost:8000/docs")
    print(f"   数据库: {DB_PATH}")
    if not DEEPSEEK_API_KEY:
        print("   [!] 未设置 DEEPSEEK_API_KEY，AI 解卦不可用")
        print("   设置方法: set DEEPSEEK_API_KEY=your_key  (Windows)")
    uvicorn.run(app, host="0.0.0.0", port=8000)