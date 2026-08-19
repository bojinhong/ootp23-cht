#!/usr/bin/env python3
"""以官方原始檔為基底，重建 text/gui_translations.xml 的 <KR> 中文翻譯。

合併規則（每筆以 HCS 的 i 屬性對應，只動 <KR>）：

  0. TEAM_NAMES / TEAM_NICKNAMES -> 由「城市 + 綽號」兩張表組出中文，組不出來
                                     退回 <EN>。詳見下面球隊名稱那一段的說明。
  1. OVERRIDES 有這個 i          -> 用人工翻譯（機翻的 <CN> 沒救時走這條）。
  2. 舊檔有這筆、<KR> 不是韓文、
     且 <KR> != <CN>              -> 保留舊檔的值（既有中文翻譯，或刻意留著的
                                     英文縮寫如 %a OBP、AL、TFBL）。
  3. 基底 <CN> 有中文             -> 用 <CN> 轉繁體填入。會走到這裡的是：
                                     韓文未翻的、<KR> 直接複製 <CN> 沒轉繁的、
                                     以及新版新增的條目。
  4. 韓文但 <CN> 沒中文可用      -> 退回填 <EN>（如 TOPPS、iPhone 13）。
  5. 其餘                         -> 原樣保留基底的 <KR>。

規則 2 的 `<KR> != <CN>` 是給 LEAGUE_NAMES 用的：那一段的 <KR> 整段都是直接
複製簡體 <CN>，靠這個條件才會落到規則 3 去轉繁。

規則 3 只套用在 CN_FILL_SECTIONS 列出的段落。TEAM_NAMES / TEAM_NICKNAMES 的
<CN> 是不能用的機翻（Reading Fightin Phils -> 「閱讀格鬥菲爾斯」），那兩段要
人工翻，不要讓這支程式去填。

其他標籤（EN / DC / ES / JP / CN）與 HCS 屬性一律沿用基底，不做任何改動。

原始檔的 KR/ES/JP/CN 欄位有個上游的毛病：實體被逸出兩次（<EN> 寫 &#39; 但
<CN> 寫 &amp;#39;），照抄的話遊戲裡會直接印出 &#39;。從 <CN> 轉過來的值會順手
還原成一層，既有的翻譯則不動。

需要 opencc：
    pip install opencc-python-reimplemented

用法:
    python3 tools/merge_gui.py                     # 基底 + text -> text
    python3 tools/merge_gui.py BASE.xml OLD.xml OUT.xml
    python3 tools/merge_gui.py --verify            # 只檢查不寫檔

沒有 temp/gui_translations.xml 時，會拿 text/gui_translations.xml 自己當基底，
等於就地把還沒中文化的部分補起來。
"""

import html
import os
import re
import shutil
import sys

DEFAULT_BASE = "temp/gui_translations.xml"
FALLBACK_BASE = "text/gui_translations.xml"
DEFAULT_OLD = "text/gui_translations.xml"
DEFAULT_OUT = "text/gui_translations.xml"

# 轉繁體用的 opencc 設定。s2tw = 簡體 -> 台灣正體字，只換字不換詞。
# 之後若要一併把「設置/數據/信息」換成「設定/資料/資訊」，改成 s2twp 再重跑。
OPENCC_CONFIG = "s2tw"

# 只有這兩段的 <CN> 堪用，可以拿來自動填 <KR>
CN_FILL_SECTIONS = {"HARD_CODED_STRINGS", "LEAGUE_NAMES"}

DOUBLE_ESCAPED_RE = re.compile(r"&amp;(#\d+|[a-zA-Z]+);")
CJK_RE = re.compile(r"[一-鿿぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")
SECTION_RE = re.compile(
    r"<(?P<sec>HARD_CODED_STRINGS|TEAM_NAMES|TEAM_NICKNAMES|TEAM_ABBR|LEAGUE_NAMES)>"
    r"(?P<body>.*?)</(?P=sec)>", re.S)
HCS_RE = re.compile(r'<HCS i="(?P<i>\d+)">(?P<body>.*?)</HCS>', re.S)
ALL_TAGS = ["EN", "DC", "KR", "ES", "JP", "CN"]

# ---------------------------------------------------------------------------
# 人工翻譯。值寫純文字就好，寫檔時才做 XML 逸出。
# ---------------------------------------------------------------------------

# LEAGUE_NAMES：<CN> 幾乎整段是機翻，錯得離譜的都列在這裡。
# 沒列到的（博卡奇卡北區、大西洋聯盟…）機翻是對的，交給規則 3 轉繁即可。
# 純縮寫（TFBL / SILP / AL / NL / LG / SL1 / FD1…）沿用英文，不翻。
OVERRIDES_LEAGUE = {
    "7693": "博卡奇卡東北區",       # CN 只寫「东北部」
    "7696": "加美分區",             # Can-Am Division，CN 誤作「加美事业部」
    "7699": "乙級",                 # Classement B
    "7702": "A組",                  # Grupo A
    "7708": "山區分區",             # Mountain Division，CN 誤作「山地师」
    "7720": "加美協會",             # CN 誤作「加拿大裔美国人协会」
    "7725": "多明尼加新人聯盟",     # Dominican Rookie League
    "7726": "2A中區",               # Double-A Central，CN 誤作「双A中环」
    "7727": "2A東北區",
    "7728": "2A南區",
    "7732": "高階1A中區",           # High-A Central
    "7733": "高階1A東區",
    "7734": "高階1A西區",
    "7735": "韓國二軍聯盟",         # Korean Futures League，CN 誤作「期货」
    "7738": "墨西哥棒球聯盟",       # Liga Mexicana de Beisbol
    "7739": "低階1A東區",           # Low-A East
    "7740": "低階1A東南區",
    "7741": "低階1A西區",
    "7743": "NPB 2A",               # NPB Double A
    "7746": "古巴全國棒球聯賽",     # Serie Nacional，CN 誤作「意甲国家棒球」
    "7749": "3A東區",               # Triple-A East，CN 誤作「三甲东」
    "7750": "3A西區",
    "7753": "委內瑞拉新人聯盟",
    "7773": "菁英級聯賽",           # Division Elite（法國最高層級）
    "7774": "法國甲級聯賽",         # French Division I
    "7776": "墨西哥棒球聯盟",
    "13002": "甲級",                # Division 1
    "13003": "慶尚",                # Gyeongsang
    "13004": "北區",                # Norte
    "13005": "加美",                # CanAm
    "13006": "南區",                # Sud
    "17070": "德國甲級南區",        # 1. Bundesliga Sud
    "17071": "德國甲級北區",        # 1. Bundesliga Nord
    "18432": "菁英級",              # Elite
    "23298": "奧地利棒球甲級聯盟",  # Bundesliga 是聯邦聯賽，不是「德甲」
}

# HARD_CODED_STRINGS：<CN> 語意明顯錯掉的（多半是棒球術語被當一般名詞翻）。
# 用語對齊檔案裡既有的譯法：waiver=釋出、posted player=發佈球員、
# minors=小聯盟、draft=選秀、Perfect Team=完美球隊、opening day=開幕。
OVERRIDES_HCS = {
    # 內野的「內」被寫成簡體的「内」，是舊檔就有的錯字
    "13053": "內野",
    "13929": "內野位置",
    "15863": "但是 %bpn 只是把它帶到了內野",
    "18785": "內野安打",
    "23307": "歡迎來到 OOTP 求職中心，這裡會列出願意提供你工作的球隊。你目前的"
             "遊戲模式是「%m」，可以在<team control settings:page#%p>中變更。你"
             "目前的聲望等級為「%r」。<your career:page#%h>的成績越好，聲望就越"
             "高，收到的工作邀約也越多",
    "23310": "自動保護大聯盟年資低於 X 年的球員",   # players 不是玩家
    "23312": "已建立 %d 名球員",
    "23316": "此次選秀的最後一次匯出已自動匯入",     # draft 不是草稿
    "23318": "與 %team 平手",
    "23323": "熱門賣單",                             # 不是「暢銷訂單」
    "23325": "若要載入先前遊戲的購買紀錄，請確認舊版 App 已更新到最新版，在舊版"
             " App 中按下「匯出賽季」按鈕並依照指示操作。然後回到這裡輸入您的電"
             "子郵件，並索取下一步要輸入的驗證碼",
    "23334": "您的賽季已在此裝置上還原",             # seasons 不是季節
    "23337": "以 %a 次盜壘領先 %l",                  # 不是「進入被盜基地」
    "23338": "將該場比賽的陣容轉為一次性陣容並繼續貼上",
    "23349": "排名卡片",
    "23350": "從錦標賽排名中獲得卡片",               # standing 不是站立
    "23352": "準備球隊圖像",
    "23353": "該球員尚未通過釋出程序",               # waivers = 釋出
    "23355": "您確定要從關注清單中移除所有球員嗎",
    "23360": "使用 3D 開包畫面",
    "23362": "DEF潛力",                              # Pot = Potential，不是鍋
    "23363": "主守位守備潛力",
    "23364": "重新載入 Perfect Draft",
    "23366": "測試煙火",
    "23372": "顯示煙火發射器",
    "23373": "使用預設日間天空盒",
    "23375": "Topps 系列",
    "23377": "奧地利棒球甲級聯盟",
    "23379": "完美球隊模式仍在開發中，即將透過免費遊戲更新推出",
    "23392": "您的完美球隊帳戶已被停權或刪除。{nl}%s{nl}請查看與此帳戶關聯的"
             "電子郵件以獲取更多細節",
    "23393": "無法建立您的球隊。目前球隊建立功能已停用，請在幾分鐘後重試",
    "23394": "無法建立您的球隊。與此帳戶關聯的球隊已被停權或刪除",
    "23395": "無法同步球員，請重試",                 # players 不是播放器
    "23398": "您的帳戶被限制參加選秀",
    "23401": "購買 2022 年或歷史賽季",
    "23405": "每天登入以延續您的連續登入紀錄，天天都能獲得新獎勵。新的一天從 "
             "UTC 午夜開始",
    "23407": "否 - 從開幕日開始",
    "23408": "是 - 依球員表現",
    "23409": "否 - 開幕日能力值",                    # ratings 不是收視率
    "23410": "否 - 開幕日名單",
    "23412": "否 - 開幕日狀態",
    "23417": "僅限死球（1920 以前）時代",
    "23418": "僅限重生（1921-1945）時代",
    "23419": "僅限黃金歲月（1946-1960）時代",
    "23420": "僅限繁榮（1961-1979）時代",
    "23421": "僅限守備（1980-1992）時代",            # Defense 不是國防
    "23422": "僅限強打（1993-2004）時代",            # Power 不是權力
    "23423": "僅限現代（2005+）時代",
    "23433": "從伺服器重新載入卡片列表",
    "23435": "載入賽季",
    "23436": "檢視小聯盟總覽",                       # minors 不是未成年人
    "23437": "檢視小聯盟名單",
    "23438": "備用陣容 vs 右投",
    "23439": "備用陣容 vs 左投",
    "23440": "年代",
    "23441": "煙火",
    "23442": "顯示卡片發光與泛光效果（影響效能",
    "23443": "MinD",                                 # 三個都是欄位縮寫，別翻
    "23444": "MinG",
    "23445": "MinB",
    "23446": "下載聯盟檔案（DEBUG",
    "23447": "失去 %p（歷史陣容",
    "23450": "失去 %p（歷史交易",
    "23453": "編輯預設陣容",
    "23454": "編輯備用陣容",
    "23463": "保留（%",
    "23469": "將球員列入傷兵名單時發生錯誤！請先騰出名單空間再將他放入 IL",
    "23470": "整體攻擊指數",                         # On-Base+Slug. Pct = OPS
    "23473": "請點擊翻面的卡片以揭曉",
    "23478": "發佈球員",                             # posted player
    "23482": "無（抽籤已停用",                       # lottery = 選秀抽籤
    "23486": "檢查卡包中",
    "23489": "取得自選卡包資料中",
    "23490": "您目前沒有任何自選卡包",
    "23491": "請選擇要開啟的自選卡包",
    "23492": "取得自選卡包資料時發生錯誤",
    "23494": "請選擇 %n 張卡片並按下 SUBMIT PICK 按鈕確認",
    "23495": "請選擇一張卡片並按下 SUBMIT PICK 按鈕確認",
    "23498": "您可以從首頁開啟自選卡包",
    "23501": "無法提交自選卡包的選擇",
    "23502": "從 XML 檔案載入/更新球隊制服與球隊顏色",
    "23504": "載入包含球隊、球衣顏色與其他屬性的 XML 檔案。必要時會建立備用球衣",
    "23507": "請選擇 %n 張卡片",
    "23509": "開啟自選卡包",
    "23512": "L10 價格（降冪",
    "23513": "L10 價格（升冪",
    "23514": "重設所有主場/客場制服貼圖",
    "23515": "你確定嗎？{nl}這將刪除並重新載入資料庫中每支球隊的隊徽檔案",
    "23516": "你確定嗎？{nl}這將刪除並重新建立資料庫中每支球隊的貼圖檔案",
    "23517": "刪除並產生球帽貼圖檔案中",
    "23518": "刪除並產生球衣貼圖檔案中",
    "23519": "刪除並產生球褲貼圖檔案中",
    "23521": "這個聯盟沒有備份！按「F1」鍵瞭解如何備份存檔",
    "23541": "您想為所有球隊載入所有顏色的 XML 檔案嗎？{nl}這將新增備用制服並"
             "更新現有的制服",
    "23545": "已開啟的自選卡包",
    "23546": "開啟了一個自選卡包",
    "23547": "已選擇的自選卡包",                     # CN 是「精選精選包」
    "23548": "選擇了一個自選卡包",
    "23549": "Topps BUNT 系列",
}

# TEAM_NAMES / TEAM_NICKNAMES 整體還沒中文化，這裡只補舊檔殘留的簡體字。
OVERRIDES_TEAM = {
    "21658": "韓華鷹",              # 舊檔寫成「韓华鹰隊」
}

OVERRIDES = {}
OVERRIDES.update(OVERRIDES_TEAM)
OVERRIDES.update(OVERRIDES_LEAGUE)
OVERRIDES.update(OVERRIDES_HCS)


# ---------------------------------------------------------------------------
# 球隊名稱（TEAM_NAMES / TEAM_NICKNAMES）
#
# 這兩段的 <CN> 是不能用的機翻（Reading Fightin Phils -> 「閱讀格鬥菲爾斯」），
# 所以不從 <CN> 來，改用「城市 + 綽號」兩張表去組：
#
#   TEAM_NAMES      = 城市中文 + 綽號中文       例：托萊多 + 泥母雞
#   TEAM_NICKNAMES  = 綽號中文                  例：泥母雞
#
# 綽號用「由右往左找最長的、在 TEAM_NICK 裡的字尾」來切，所以 Round Rock
# Express 會切成 Round Rock | Express 而不是 Round | Rock Express。
#
# 組不出來就退回 <EN> 英文原名——歐洲各國聯盟那 69 支（Sénart Templiers、
# Cardion Hrosi Brno Baseball…）沒有通用中文譯名，硬翻只會變成自創名字。
# 這也讓改版新增的球隊自動落在英文，不會生出亂翻的中文。
# ---------------------------------------------------------------------------

# 綽號：英文 -> 中文。造出來的隊名（Albirex、wiz、Y'alls）維持英文。
TEAM_NICK = {
"66ers":"66人","Aces":"王牌","Acereros":"鋼鐵人","Admirals":"上將","Aigles":"飛鷹","Alazanes":"栗馬",
"Albirex":"Albirex","Algodoneros":"棉農","Amberjacks":"紅甘","Anchors":"船錨","Angels":"天使",
"Apollos":"阿波羅","AquaSox":"水襪","Astro Planets":"太空行星","Astros":"太空人","Athletics":"運動家",
"Aviators":"飛行員","Avispas":"黃蜂","Bandits":"強盜","Barnstormers":"特技飛人","Barons":"男爵",
"Bats":"蝙蝠","BayStars":"灣星","Bay Stars":"灣星","Baysox":"灣襪","Bears":"熊","Beavers":"海狸",
"Bees":"蜜蜂","Biscuits":"餅乾","Bisons":"野牛","Blacks":"黑隊","Blue Crabs":"藍蟹","Blue Jays":"藍鳥",
"Blue Rocks":"藍岩","Blue Sox":"藍襪","Blue Wahoos":"藍刺鮁","BlueClaws":"藍螯蟹","Boomers":"轟炸手",
"Boulders":"巨石","Braves":"勇士","Bravos":"勇士","Brewers":"釀酒人","Brothers":"兄弟",
"Buffaloes":"猛牛","Bulls":"公牛","Canadians":"加拿大人","Canaries":"金絲雀","Cannon Ballers":"砲彈手",
"Capitales":"首都","Captains":"船長","Cardinals":"紅雀","Carp":"鯉魚","Cavalry":"騎兵",
"Cazadores":"獵人","Chiefs":"酋長","Chihuahuas":"吉娃娃","Chukars":"石雞","Clippers":"快船",
"Cocodrilos":"鱷魚","Cougars":"美洲獅","Cowboys":"牛仔","Crawdads":"小龍蝦","Crushers":"粉碎者",
"Cubs":"小熊","Curve":"曲球","Cyclones":"旋風","Dash":"衝刺","Devils":"魔鬼","Diablos Rojos":"紅魔",
"Diamond Hoppers":"鑽石跳者","Diamond Pegasus":"鑽石天馬","Diamondbacks":"響尾蛇","Dinos":"恐龍",
"Dodgers":"道奇","Dogecoin":"狗狗幣","Dogs":"狗","Dragons":"龍","Drillers":"鑽井工","Drive":"驅動",
"Ducks":"鴨","Dust Devils":"塵捲風","Eagles":"鷹","El Aguila":"老鷹","Elefantes":"大象",
"Elephants":"象","Emeralds":"翡翠","Explorers":"探險家","Express":"快車","Fightin Phils":"費城人",
"Fighters":"鬥士","Fighting Dogs":"鬥犬","Fireflies":"螢火蟲","Fisher Cats":"漁貂",
"Flying Squirrels":"飛鼠","Flying Tigers":"飛虎","Fuego":"火焰","Future Dreams":"未來夢想",
"Gallos":"鬥雞","Ganaderos":"牧人","Generales":"將軍","Giants":"巨人","Golden Braves":"黃金勇士",
"Golden Eagles":"金鷹","Goldeyes":"金眼","Grandserows":"大羚羊","Grasshoppers":"蚱蜢",
"GreenJackets":"綠外套","Grizzlies":"灰熊","Guardians":"守護者","Guerreros":"戰士",
"Hammerheads":"槌頭鯊","Hawks":"鷹","Heat":"熱火","Heat Bears":"熱熊","Heroes":"英雄","Hillcats":"山貓",
"Honey Hunters":"獵蜜人","Hooks":"魚鉤","Hops":"啤酒花","Hot Rods":"改裝車","Huracanes":"颶風",
"Indians":"印第安人","Indigo Socks":"藍染襪","Indios":"印第安人","Invaders":"侵略者","IronPigs":"鐵豬",
"Ironbirds":"鐵鳥","Islanders":"島民","Isotopes":"同位素","Jackals":"豺狼","Jumbo Shrimp":"大蝦",
"Kernels":"玉米粒","Knights":"騎士","Korea":"韓國","Landers":"登陸者","Legends":"傳奇",
"Lenadores":"伐木工","Leones":"獅","Lions":"獅","Lookouts":"瞭望者","Loons":"潛鳥","Lugnuts":"螺帽",
"Mammoths":"長毛象","Mandarin Pirates":"蜜柑海盜","Marauders":"掠奪者","Mariachis":"街頭樂隊",
"Mariners":"水手","Marines":"海洋","Marlins":"馬林魚","Mets":"大都會","Mighty Mussels":"猛貽貝",
"Milkmen":"送奶工","Million Stars":"百萬之星","Miners":"礦工","Missions":"教會","Monarchs":"帝王",
"Monkeys":"猿","Mud Hens":"泥母雞","Mudcats":"泥鯰","Mustangs":"野馬","Naranjas":"柳橙",
"Nationals":"國民","Naturals":"自然人","Nuts":"堅果","Olive Guyners":"橄欖","Olmecas":"奧爾梅克",
"Orioles":"金鶯","Osos":"熊","Otters":"水獺","PaddleHeads":"槳頭","Padres":"教士","Patriots":"愛國者",
"Pelicans":"鵜鶘","Pericos":"鸚鵡","Phillies":"費城人","Piratas":"海盜","Pirates":"海盜","Ports":"港口",
"Power":"力量","Pupfish":"鱂魚","Quakes":"地震","RailCats":"鐵路貓","RailRiders":"鐵路騎士",
"Railroaders":"鐵路工","Rainiers":"雷尼爾","Rangers":"遊騎兵","Raptors":"猛禽","Rawhide":"生皮",
"Rays":"光芒","Red Sox":"紅襪","Red Wings":"紅翼","RedHawks":"紅鷹","RedHopes":"紅希望",
"Redbirds":"紅鳥","Reds":"紅人","Renegades":"叛徒","Reserves":"後備","Revolution":"革命",
"Rhinos":"犀牛","Rieleros":"鐵路工","River Bandits":"河盜","River Cats":"河貓","RiverDogs":"河狗",
"RiverPigs":"河豬","RockHounds":"尋石者","Rockers":"搖滾客","Rockies":"洛磯","RoughRiders":"莽騎兵",
"Royals":"皇家","RubberDucks":"橡皮鴨","Rumble Ponies":"隆隆小馬","Sabuesos":"獵犬","Saguaros":"仙人掌",
"Saints":"聖徒","Saltdogs":"鹽狗","Saraperos":"披毯人","Sea Dogs":"海狗","SeaWolves":"海狼",
"Seaweed":"海藻","Senators":"參議員","Shorebirds":"濱鳥","Shuckers":"剝殼人","Silverados":"銀彈",
"Skeeters":"蚊子","Slammers":"重擊手","Smokies":"煙山","Snappers":"鱷龜","Sod Poodles":"草原犬鼠",
"Sounds":"之聲","Stompers":"踩踏者","Storm":"風暴","Storm Chasers":"風暴追逐者","Stripers":"條紋鱸",
"Sturgeon":"鱘魚","Sultanes":"蘇丹","Surge":"浪湧","Swallows":"燕子","Tarpons":"大海鰱",
"Tecolotes":"貓頭鷹","Threshers":"長尾鯊","ThunderBolts":"雷霆","Thunderbirds":"雷鳥","Tides":"潮汐",
"Tigers":"老虎","Tigres":"老虎","Timber Rattlers":"林響尾蛇","TinCaps":"錫帽","Titans":"泰坦",
"Toronjeros":"柚農","Toros":"公牛","Tortugas":"海龜","Tourists":"遊客","Train Robbers":"火車大盜",
"Trash Pandas":"垃圾熊貓","Travelers":"旅行者","Triggers":"扳機","Tuatara":"喙頭蜥","Twins":"雙子",
"Unicorns":"獨角獸","ValleyCats":"谷貓","Vegueros":"菸農","Vibes":"律動","Voyagers":"航行者",
"White Sox":"白襪","Whitecaps":"白浪","Wild":"野性","Wild Raptors":"野猛禽","Wild Things":"野物",
"Wind":"風","Wind Surge":"風湧","Wood Ducks":"林鴛鴦","Woodpeckers":"啄木鳥","Woolly Mammoths":"長毛象",
"Y'alls":"Y'alls","Yankees":"洋基","Yard Goats":"調車山羊","wiz":"wiz",
}

# 城市／母企業：英文 -> 中文
TEAM_CITY = {
"Aberdeen":"亞伯丁","Aguascalientes":"阿瓜斯卡連特斯","Akron":"阿克倫","Albuquerque":"阿爾伯克基",
"Alpine":"阿爾派恩","Altoona":"阿爾圖納","Amarillo":"阿馬里洛","Arizona":"亞利桑那","Arkansas":"阿肯色",
"Artemisa":"阿特米薩","Asheville":"艾許維爾","Atlanta":"亞特蘭大","Auckland":"奧克蘭","Augusta":"奧古斯塔",
"Bakersfield":"貝克斯菲爾德","Baltimore":"巴爾的摩","Beloit":"貝洛伊特","Billings":"比林斯","Biloxi":"比洛克西",
"Binghamton":"賓漢頓","Birmingham":"伯明罕","Birmingham-Bloomfield":"伯明罕-布隆菲爾德","Boise":"博伊西",
"Boston":"波士頓","Bowling Green":"鮑林格林","Bradenton":"布雷登頓","Brisbane":"布里斯本",
"Brooklyn":"布魯克林","Buffalo":"水牛城","California":"加州","Camaguey":"卡馬圭","Campeche":"坎佩切",
"Carolina":"卡羅來納","Cedar Rapids":"錫達拉皮茲","Changwon":"昌原","Charleston":"查爾斯頓",
"Charlotte":"夏洛特","Chiba Lotte":"千葉羅德","Chicago":"芝加哥","Chunichi":"中日",
"Ciego de Avila":"謝戈德阿維拉","Cienfuegos":"西恩富戈斯","Cincinnati":"辛辛那提","Clearwater":"清水",
"Cleburne":"克萊本","Cleveland":"克利夫蘭","Colorado":"科羅拉多","Columbia":"哥倫比亞","Columbus":"哥倫布",
"Corpus Christi":"科珀斯克里斯蒂","Dayton":"代頓","Daytona":"戴通納","Delmarva":"德爾馬瓦","Detroit":"底特律",
"Doosan":"斗山","Dos Laredos":"雙拉雷多","Down East":"唐伊斯特","Dunedin":"敦尼丁","Durango":"杜蘭戈",
"Durham":"達勒姆","Eastside":"東城","Ehime":"愛媛","El Paso":"埃爾帕索","Erie":"伊利","Eugene":"尤金",
"Evansville":"埃文斯維爾","Everett":"埃弗里特","Fargo-Moorhead":"法戈-穆爾黑德","Fayetteville":"費耶特維爾",
"Florence":"佛羅倫斯","Fort Myers":"邁爾斯堡","Fort Wayne":"韋恩堡","Fredericksburg":"弗雷德里克斯堡",
"Fresno":"弗雷斯諾","Frisco":"弗里斯科","Fubon":"富邦","Fukui":"福井","Fukuoka SoftBank":"福岡軟銀",
"Fukushima":"福島","Ganghwa":"江華","Garden City":"加登城","Gary SouthShore":"蓋瑞南岸",
"Gastonia":"加斯托尼亞","Gateway":"門戶","Geelong":"吉隆","Georgia":"喬治亞","Goyang":"高陽",
"Grand Junction":"大章克申","Granma":"格拉瑪","Great Falls":"大瀑布城","Great Lakes":"五大湖",
"Greensboro":"格林斯伯勒","Greenville":"格林維爾","Guadalajara":"瓜達拉哈拉","Guantanamo":"關塔那摩",
"Gunma":"群馬","Gwinnett":"格威內特","Gyeongsan":"慶山","Hampyeong":"咸平","Hanshin":"阪神",
"Hanwha":"韓華","Harrisburg":"哈里斯堡","Hartford":"哈特福","Hickory":"希科里","High Point":"高點",
"Hillsboro":"希爾斯伯勒","Hiroshima Toyo":"廣島東洋","Hokkaido":"北海道","Holguin":"奧爾金",
"Houston":"休士頓","Hudson Valley":"哈德遜谷","Ibaraki":"茨城","Icheon":"利川","Idaho Falls":"愛達荷佛斯",
"Iksan":"益山","Indianapolis":"印第安納波利斯","Industriales":"工業","Inland Empire":"內陸帝國",
"Iowa":"愛荷華","Ishikawa":"石川","Isla de la Juventud":"青年島","Jacksonville":"傑克遜維爾",
"Jersey Shore":"澤西海岸","Joliet":"喬利埃特","Jupiter":"朱庇特","KIA":"起亞","Kagawa":"香川",
"Kanagawa":"神奈川","Kane County":"凱恩郡","Kannapolis":"坎納波利斯","Kansas City":"堪薩斯城",
"Kiwoom":"Kiwoom","Kochi":"高知","LG":"LG","Lake County":"萊克郡","Lake Elsinore":"埃爾西諾湖",
"Lake Erie":"伊利湖","Lakeland":"萊克蘭","Lancaster":"蘭卡斯特","Lansing":"蘭辛","Las Tunas":"拉斯圖納斯",
"Las Vegas":"拉斯維加斯","Lehigh Valley":"利哈伊谷","Leon":"萊昂","Lexington":"列克星敦","Lincoln":"林肯",
"Long Island":"長島","Los Angeles":"洛杉磯","Lotte":"樂天","Louisville":"路易維爾","Lynchburg":"林奇堡",
"Martinez":"馬丁尼茲","Matanzas":"馬坦薩斯","Mayabeque":"馬亞貝克","Melbourne":"墨爾本","Memphis":"曼菲斯",
"Mexico":"墨西哥","Miami":"邁阿密","Midland":"米德蘭","Milwaukee":"密爾瓦基","Minnesota":"明尼蘇達",
"Mississippi":"密西西比","Missoula":"米蘇拉","Modesto":"莫德斯托","Monclova":"蒙克洛瓦","Monterey":"蒙特雷",
"Monterrey":"蒙特雷","Montgomery":"蒙哥馬利","Myrtle Beach":"默特爾比奇","NC":"NC","Napa":"納帕",
"Nashville":"納許維爾","New Hampshire":"新罕布夏","New Jersey":"新澤西","New York":"紐約","Niigata":"新潟",
"Norfolk":"諾福克","Northwest Arkansas":"西北阿肯色","Oakland":"奧克蘭","Oaxaca":"瓦哈卡",
"Ocean Shiga":"滋賀","Ogden":"奧格登","Oklahoma City":"奧克拉荷馬城","Omaha":"奧馬哈","Orix":"歐力士",
"Ottawa":"渥太華","Palm Beach":"棕櫚灘","Pensacola":"彭薩科拉","Peoria":"皮奧里亞","Perth":"伯斯",
"Philadelphia":"費城","Pinar del Rio":"比那爾德里奧","Pittsburg":"匹茲堡","Pittsburgh":"匹茲堡",
"Plattsburgh":"普拉茨堡","Portland":"波特蘭","Puebla":"普埃布拉","Puerto Rico":"波多黎各",
"Quad Cities":"四城","Quebec":"魁北克","Quintana Roo":"金塔納羅奧","Rakuten":"樂天",
"Rancho Cucamonga":"蘭喬庫卡蒙加","Reading":"雷丁","Reno":"雷諾","Richmond":"里奇蒙","Rochester":"羅徹斯特",
"Rocket City":"火箭城","Rocky Mountain":"落磯山","Rome":"羅馬","Roswell":"羅斯威爾","Round Rock":"圓石城",
"Ruidoso":"魯伊多索","SSG":"SSG","Sacramento":"沙加緬度","Saitama Musashi":"埼玉武藏",
"Saitama Seibu":"埼玉西武","Salem":"塞勒姆","Salt Lake":"鹽湖","Saltillo":"薩爾提約","Samsung":"三星",
"San Antonio":"聖安東尼奧","San Diego":"聖地牙哥","San Francisco":"舊金山","San Jose":"聖荷西",
"Sancti Spiritus":"聖斯皮里圖斯","Sangdong":"上洞","Santa Cruz":"聖克魯茲","Santa Fe":"聖塔菲",
"Santiago de Cuba":"聖地亞哥","Saranac Lake":"薩拉納克湖","Schaumburg":"紹姆堡","Scranton WB":"斯克蘭頓",
"Seattle":"西雅圖","Seosan":"瑞山","Shinano":"信濃","Sioux City":"蘇城","Sioux Falls":"蘇瀑",
"Somerset":"薩默塞特","Sonoma":"索諾瑪","South Bend":"南本德","Southern Illinois":"南伊利諾",
"Southern Maryland":"南馬里蘭","Spokane":"斯波坎","Springfield":"斯普林菲爾德","St. Louis":"聖路易",
"St. Lucie":"聖露西","St. Paul":"聖保羅","Stockton":"斯托克頓","Sugar Land":"休格蘭",
"Sussex County":"薩塞克斯郡","Sydney":"雪梨","Syracuse":"雪城","Tabasco":"塔巴斯科","Tacoma":"塔科馬",
"Tampa":"坦帕","Tampa Bay":"坦帕灣","Taoyuan":"桃園","Tennessee":"田納西","Texas":"德州",
"Tijuana":"提華納","Tochigi":"栃木","Tohoku Rakuten":"東北樂天","Tokushima":"德島",
"Tokyo Yakult":"東京養樂多","Toledo":"托萊多","Toronto":"多倫多","Toyama GRN":"富山","Tri-City":"三城",
"Trinidad":"千里達","Trois-Rivieres":"三河城","Tucson":"土桑","Tulsa":"塔爾薩","Tupper Lake":"塔珀湖",
"Union Laguna":"拉古納聯","Utica":"尤蒂卡","Vallejo":"瓦列霍","Vancouver":"溫哥華","Veracruz":"韋拉克魯斯",
"Villa Clara":"比亞克拉拉","Visalia":"維薩利亞","Wasco":"瓦斯科","Washington":"華盛頓",
"West Michigan":"西密西根","West Virginia":"西維吉尼亞","Westside":"西城","White Sands":"白沙",
"Wichita":"威奇托","Wilmington":"威明頓","Windy City":"風城","Winnipeg":"溫尼伯",
"Winston-Salem":"溫斯頓塞勒姆","Wisconsin":"威斯康辛","Worcester":"伍斯特","Yokohama DeNA":"橫濱DeNA",
"Yokohama":"橫濱","Yomiuri":"讀賣","York":"約克","Yucatan":"猶加敦","kt":"kt","Bowie":"鮑伊",
"Chattanooga":"查塔努加","Canberra":"坎培拉","Adelaide":"阿德萊德","Hokkaido Nippon-Ham":"北海道日本火腿",
"Hokkaido Nippon Ham":"北海道日本火腿","Seibu":"西武",
}

# 不照「城市+綽號」組合規則的球隊，直接指定 (全名, 綽號)。key 是 HCS 的 i，
# 因為中職的味全龍在 TEAM_NAMES 出現兩次，光靠英文隊名分不出一軍二軍。
# 每支要寫兩個 i：TEAM_NAMES 的與 TEAM_NICKNAMES 的（後者 = 前者 + 489）。
# verify() 會檢查每個 key 都真的被用到，改版後 i 跑掉會直接報錯。
TEAM_BY_I = {
    "21463": ("明尼蘇達雙城", "雙城"),
    "21671": ("中信兄弟", "兄弟"),
    "21672": ("樂天桃猿", "桃猿"),
    "21673": ("統一獅", "獅"),
    "21674": ("富邦悍將", "悍將"),
    "21675": ("味全龍", "龍"),
    "21676": ("桃園象二軍", "象二軍"),
    "21677": ("樂天桃猿二軍", "桃猿二軍"),
    "21678": ("統一獅二軍", "獅二軍"),
    "21679": ("富邦悍將二軍", "悍將二軍"),
    "21680": ("味全龍二軍", "龍二軍"),
    # 以上是 TEAM_NAMES 的 i，以下是同幾支球隊在 TEAM_NICKNAMES 的 i
    "21952": ("明尼蘇達雙城", "雙城"),
    "22160": ("中信兄弟", "兄弟"),
    "22161": ("樂天桃猿", "桃猿"),
    "22162": ("統一獅", "獅"),
    "22163": ("富邦悍將", "悍將"),
    "22164": ("味全龍", "龍"),
    "22165": ("桃園象二軍", "象二軍"),
    "22166": ("樂天桃猿二軍", "桃猿二軍"),
    "22167": ("統一獅二軍", "獅二軍"),
    "22168": ("富邦悍將二軍", "悍將二軍"),
    "22169": ("味全龍二軍", "龍二軍"),
}

# 沒有通用中文譯名、退回英文的球隊，在 TEAM_NICKNAMES 要顯示的短名。
TEAM_EN_NICK = {
"Parma Clima":"Clima","UnipolSai Bologna BC 1953":"BC 1953",
"T&A San Marino":"San Marino","Godo Knights":"Knights","Rangers Redipuglia":"Rangers",
"Nettuno BC 1945":"BC 1945","Senago Milano United":"United",
"Torino 48 B.C. Grizzles B.C. 1948":"Grizzles","Macerata Angels":"Angels",
"Collecchio Baseball Club":"Collecchio","L&D Amsterdam Pirates":"Pirates",
"Hoofddorp Pioniers":"Pioniers","HCAW Baseball":"HCAW","Curacao Neptunus":"Neptunus",
"DSS Kinheim Honkbal":"Kinheim","De Glaskoning Twins":"Twins","Silicon Storks":"Storks",
"Quick Amersfoort Cityside Apartments":"Quick Amersfoort","Bonn Capitals":"Capitals",
"Cologne Cardinals":"Cardinals","Dohren Wild Farmers":"Wild Farmers",
"Hamburg Stealers":"Stealers","Paderborn Untouchables":"Untouchables",
"Solingen Aligators":"Aligators","Berlin Flamingos":"Flamingos",
"Dortmund Wanderers":"Wanderers","Buchbinder Legionare":"Legionare",
"Heidenheim Heidekopfe":"Heidekopfe","Mainz Athletics":"Athletics",
"Mannheim Tornados":"Tornados","Munchen-Haar Disciples":"Disciples","Stuttgart Reds":"Reds",
"IT sure Falcons":"Falcons","Tubingen Hawks":"Hawks","Rouen Huskies":"Huskies",
"Savigny-sur-Orge Lions":"Lions","Toulouse Tigers":"Tigers",
"Montigny-le-Bretonneux Cougars":"Cougars","Paris Université Club":"PUC",
"La Rochelle Boucaniers":"Boucaniers","Sénart Templiers":"Templiers",
"Nice Cavigal":"Cavigal","Metz Cometz":"Cometz","Montpellier Barracudas":"Barracudas",
"Clermont-Ferrand Arvernes":"Arvernes","Blansko Olympia":"Olympia",
"Eagles Praha Baseball":"Eagles","Kotlarka Praha Baseball":"Kotlarka",
"Tempo Titans Praha Baseball":"Titans","SaBaT Praha Baseball":"SaBaT",
"Arrows Ostrava Baseball":"Arrows","Cardion Hrosi Brno Baseball":"Hrosi",
"Draci Brno Baseball":"Draci","Technika Brno Baseball":"Technika",
"Trebic Nuclears":"Nuclears","Jablonec Baseball Blesk":"Blesk",
"Sokol Hluboka Baseball":"Sokol","CB Barcelona Beisbol":"Barcelona",
"Miralbueno Zaragoza Beisbol":"Miralbueno","Tenerife Marlins":"Marlins",
"CB Viladecans Beisbol":"Viladecans","CBS Antorcha Valencia Beisbol":"Antorcha",
"Bilbao San Inazio":"San Inazio","CBS Rivas Beisbol":"Rivas",
"CBS Sant Boi Beisbol":"Sant Boi","Navarra Beisbol":"Navarra","Valencia Astros":"Astros",
"CBS Toros Pamplona Beisbol":"Toros","CBS Gava Beisbol":"Gava",
}

# 農場隊尾綴：Chicago N (AZL) Cubs Blue -> 芝加哥小熊藍 (AZL)
TEAM_SUFFIX = {"Blue": "藍", "Red": "紅", "Green": "綠", "Gold": "金", "Orange": "橙",
               "Black": "黑", "White": "白", "East": "東", "West": "西", "1": "1", "2": "2"}
# 括號裡的層級標記。Ni-Gun 當字尾接在隊名後面，其餘保留原樣掛在全名尾巴。
TEAM_TAG_SUFFIX = {"Ni-Gun": "二軍"}
TEAM_COMPLEX_RE = re.compile(
    r"^(?P<city>.+?)\s*(?:\b[NAEW]\b\s*)?\((?P<tag>[A-Za-z-]+)\)\s*(?P<rest>.+)$")

TEAM_SECTIONS = {"TEAM_NAMES", "TEAM_NICKNAMES"}


def _join(a, b):
    """兩邊都是拉丁字母時要補空白（kt + wiz），中文則不用。"""
    if a and a[-1].isascii() and b and b[0].isascii():
        return a + " " + b
    return a + b


def _split_nick(name):
    """由右往左找最長的、在 TEAM_NICK 裡的字尾，回傳 (城市英文, 綽號英文)。"""
    w = name.split()
    for k in range(len(w)):
        cand = " ".join(w[k:])
        if cand in TEAM_NICK:
            return " ".join(w[:k]), cand
    return None


def team_names(i, en):
    """回傳 (全名, 綽號)，組不出來回傳 None 表示要退回英文。"""
    if i in TEAM_BY_I:
        return TEAM_BY_I[i]

    m = TEAM_COMPLEX_RE.match(en)
    if m:
        city_en = re.sub(r"\s+[NAEW]$", "", m.group("city").strip())
        tag = m.group("tag")
        rest = re.sub(r"(?<=[a-z])(\d)$", r" \1", m.group("rest").strip())
        parts, tail = rest.split(), ""
        while parts and (parts[-1] in TEAM_SUFFIX or parts[-1] in ("Guerrero", "Robinson")):
            tail = TEAM_SUFFIX.get(parts[-1], parts[-1]) + tail
            parts.pop()
        nick_en = " ".join(parts)
        if city_en not in TEAM_CITY or nick_en not in TEAM_NICK:
            return None
        if tag in TEAM_TAG_SUFFIX:
            nick = TEAM_NICK[nick_en] + tail + TEAM_TAG_SUFFIX[tag]
            return _join(TEAM_CITY[city_en], nick), nick
        nick = TEAM_NICK[nick_en] + tail
        return f"{_join(TEAM_CITY[city_en], nick)} ({tag})", nick

    split = _split_nick(en)
    if not split:
        return None
    city_en, nick_en = split
    if city_en and city_en not in TEAM_CITY:
        return None
    nick = TEAM_NICK[nick_en]
    return (_join(TEAM_CITY[city_en], nick) if city_en else nick), nick


def team_value(section, i, en):
    """該球隊在這一段要填的值。中文組不出來就退回英文。"""
    pair = team_names(i, en)
    if pair is None:
        return en if section == "TEAM_NAMES" else TEAM_EN_NICK.get(en, en)
    return pair[0] if section == "TEAM_NAMES" else pair[1]


def load_opencc():
    try:
        from opencc import OpenCC
    except ImportError:
        sys.exit("需要 opencc，請先執行: pip install opencc-python-reimplemented")
    return OpenCC(OPENCC_CONFIG).convert


def simplified_only_chars():
    """只存在於簡體的字（自己不在自己的繁體候選裡），拿來檢查有沒有漏轉。

    要扣掉台灣標準字，否則會誤報：OpenCC 的 STCharacters 認為 群 的繁體是
    羣、才 的繁體是 纔，但台灣用的正是 群 和 才（TWVariants 就是在做這層
    還原），s2tw 的輸出本來就該長這樣。
    """
    import opencc
    d = os.path.join(os.path.dirname(opencc.__file__), "dictionary")

    tw_standard = set()
    with open(os.path.join(d, "TWVariants.txt"), encoding="utf-8") as f:
        for line in f:
            tw_standard.update(line.rstrip("\n").split("\t")[1].split(" "))

    out = set()
    with open(os.path.join(d, "STCharacters.txt"), encoding="utf-8") as f:
        for line in f:
            s, t = line.rstrip("\n").split("\t")
            if s not in t.split(" "):
                out.add(s)
    return out - tw_standard


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def tag_value(body, tag):
    m = re.search(r"<" + tag + r">(.*?)</" + tag + r">", body, re.S)
    return m.group(1) if m else None


def parse(path):
    """{i: (section, {tag: raw_value})}"""
    out = {}
    for sm in SECTION_RE.finditer(read(path)):
        for m in HCS_RE.finditer(sm.group("body")):
            out[m.group("i")] = (
                sm.group("sec"),
                {t: tag_value(m.group("body"), t) for t in ALL_TAGS})
    return out


def merge(base, old, out_path):
    convert = load_opencc()
    old_entries = parse(old)
    stats = dict(team=0, override=0, kept=0, from_cn=0, from_en=0, untouched=0)

    def fix_section(sm):
        section = sm.group("sec")

        def fix_hcs(m):
            i, body = m.group("i"), m.group("body")
            cur = tag_value(body, "KR")
            if cur is None:
                return m.group(0)
            cn = tag_value(body, "CN") or ""

            if section in TEAM_SECTIONS:
                en = html.unescape(tag_value(body, "EN") or "")
                new = html.escape(team_value(section, i, en), quote=False)
                stats["team"] += 1
            elif i in OVERRIDES:
                new = html.escape(OVERRIDES[i], quote=False)
                stats["override"] += 1
            elif (i in old_entries
                  and old_entries[i][1]["KR"] is not None
                  and not HANGUL_RE.search(html.unescape(old_entries[i][1]["KR"]))
                  and old_entries[i][1]["KR"] != old_entries[i][1]["CN"]):
                new = old_entries[i][1]["KR"]
                stats["kept"] += 1
            elif section in CN_FILL_SECTIONS and CJK_RE.search(html.unescape(cn)):
                new = DOUBLE_ESCAPED_RE.sub(r"&\1;", convert(cn))
                stats["from_cn"] += 1
            elif (section in CN_FILL_SECTIONS
                  and HANGUL_RE.search(html.unescape(cur))):
                new = tag_value(body, "EN")
                if new is None:
                    stats["untouched"] += 1
                    return m.group(0)
                stats["from_en"] += 1
            else:
                stats["untouched"] += 1
                return m.group(0)

            if new == cur:
                return m.group(0)
            return m.group(0).replace(f"<KR>{cur}</KR>", f"<KR>{new}</KR>", 1)

        return (f'<{section}>' + HCS_RE.sub(fix_hcs, sm.group("body"))
                + f'</{section}>')

    result = SECTION_RE.sub(fix_section, read(base))

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(result)
    os.replace(tmp, out_path)

    print(f"基底 {base} + 翻譯 {old} -> {out_path}")
    print(f"  球隊名稱(組表)      : {stats['team']}")
    print(f"  人工翻譯(OVERRIDES) : {stats['override']}")
    print(f"  保留舊檔的值        : {stats['kept']}")
    print(f"  由 <CN> 轉繁填入    : {stats['from_cn']}")
    print(f"  無中文、退回英文    : {stats['from_en']}")
    print(f"  原樣保留基底        : {stats['untouched']}")


def verify(out_path, base, old):
    O, B, D = parse(out_path), parse(base), parse(old)
    simp = simplified_only_chars()
    ok = True

    print(f"檢查 {out_path}")
    print(f"  HCS 筆數              : {len(O)}")
    if set(O) != set(B):
        print("  HCS 集合與基底不符!")
        ok = False

    # KR 以外的標籤必須與基底完全相同
    drift = []
    for i in O:
        if i not in B:
            continue
        for t in ALL_TAGS:
            if t != "KR" and O[i][1][t] != B[i][1][t]:
                drift.append((i, t))
    print(f"  其他標籤偏離基底      : {len(drift)}", drift[:3] if drift else "")
    ok = ok and not drift

    # 舊檔既有的中文翻譯不能掉（OVERRIDES 是刻意改的，排除）
    lost = []
    for i, (_, f) in D.items():
        kr = f["KR"]
        if (i in OVERRIDES or D[i][0] in TEAM_SECTIONS or kr is None or kr == f["CN"]
                or not CJK_RE.search(html.unescape(kr))):
            continue
        if i not in O or O[i][1]["KR"] != kr:
            lost.append(i)
    print(f"  遺失的舊中文翻譯      : {len(lost)}", lost[:5] if lost else "")
    ok = ok and not lost

    # 分段回報殘留的韓文與簡體字
    for sec in ["HARD_CODED_STRINGS", "TEAM_NAMES", "TEAM_NICKNAMES",
                "TEAM_ABBR", "LEAGUE_NAMES"]:
        rows = [(i, f["KR"]) for i, (s, f) in O.items()
                if s == sec and f["KR"] is not None]
        han = [i for i, v in rows if HANGUL_RE.search(html.unescape(v))]
        sim = [i for i, v in rows if simp & set(html.unescape(v))]
        mark = "" if sec in CN_FILL_SECTIONS or sec in TEAM_SECTIONS else "  (英文縮寫)"
        print(f"  {sec:20s} 殘留韓文 {len(han):4d} / 殘留簡體 {len(sim):3d}{mark}")
        if sec in CN_FILL_SECTIONS or sec in TEAM_SECTIONS:
            if han:
                print("      韓文:", han[:5])
            if sim:
                print("      簡體:", sim[:5])
            ok = ok and not han and not sim

    # TEAM_BY_I 的 key 必須都真的落在球隊段裡；改版後 i 跑掉要看得出來
    in_teams = {i for i, (sec, _) in O.items() if sec in TEAM_SECTIONS}
    unused = sorted(set(TEAM_BY_I) - in_teams)
    print(f"  TEAM_BY_I 沒被用到    : {len(unused)}", unused if unused else "")
    ok = ok and not unused

    print("  結果                  : " + ("PASS" if ok else "FAIL"))
    return ok


def main(argv):
    verify_only = "--verify" in argv
    argv = [a for a in argv if a != "--verify"]

    default_base = DEFAULT_BASE if os.path.exists(DEFAULT_BASE) else FALLBACK_BASE
    base = argv[0] if len(argv) > 0 else default_base
    old = argv[1] if len(argv) > 1 else DEFAULT_OLD
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT

    if verify_only:
        return 0 if verify(out, base, old) else 1

    if os.path.abspath(old) == os.path.abspath(out):
        snapshot = out + ".orig.tmp"
        shutil.copyfile(old, snapshot)
        try:
            merge(base if base != old else snapshot, snapshot, out)
            ok = verify(out, base if base != old else snapshot, snapshot)
        finally:
            os.remove(snapshot)
    else:
        merge(base, old, out)
        ok = verify(out, base, old)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
