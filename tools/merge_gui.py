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

# 轉繁體用的 opencc 設定。s2tw = 簡體 -> 台灣正體字，只換字不換詞；
# 「設置/數據/信息」這類詞交給下面的 TERM_FIXES 處理，不用 s2twp（它會連
# 不該換的地方一起換）。
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
    "23353": "該球員尚未通過讓渡程序",               # waivers = 讓渡
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

    # 用詞統一時挑出來的機翻錯譯
    "112": "%ln 已公佈本次擴編競標的得標球隊！新球隊為 %t",
    "469": "歷史演進設定",
    "969": "使用左右方向鍵切換守備佈陣",
    "1029": "最低素質",
    "1141": "用來衡量球員生涯整體水準（而非巔峰價值）的分數",
    "1604": "解除共同專員",
    "1614": "每週模擬次數",
    "1698": "素質：%qual，球員：%players",
    "1779": "將 OOOL 使用者設為共同專員",
    "1781": "您現在有一位新的共同專員。記得到「新增/編輯總教練」對話視窗，"
            "把新的共同專員指派給某位人類總教練",
    "1793": "您已在 OOOL 解除該共同專員。如有需要，請自行到「新增/編輯總教練」"
            "對話視窗手動解除",
    "1962": "這會檢查所有球隊與聯盟，確認附屬球隊的連結正確。要繼續嗎",
    "2410": "歷來戰績",
    "2430": "一般排名",
    "2633": "Out of the Park 新聞",
    "2836": "注意！附加元件並非由 OOTP Developments 正式認可或提供支援，使用風險"
            "請自負。所有版權與商標均屬於各自的擁有者。本頁的網頁連結可能連往"
            "OOTP Developments 無法掌控的網站，OOTP Developments 對這些網站及其"
            "提供的附加元件內容概不負責",
    "2880": "正在安裝創意工坊項目",
    "3272": "恭喜，您以 %dPP 買下了 %s。他會出現在您的預備名單，或以非現役卡片的"
            "形式留在卡片收藏列表中，可從主選單的「管理卡片」進入",
    "3916": "Fira Sans 標準",
    "3917": "Barlow 標準",
    "4192": "一般卡包",
    "4193": "一般卡包",
    "4466": "快速成績表 客隊",
    "4973": "例行球處理數",
    "5073": "例行球",
    "5116": "例行球比例",
    "5700": "球探目標",
    "6041": "專員中心",
    "6221": "匯入一般 PT 聯盟名單",
    "6291": "Out of the Park Baseball",
    "7304": "顯示待辦清單",
    "9914": "例行守備之間的延遲",
    "10797": "點此返回一般主畫面",
    "11031": "一般聯盟新聞",
    "11349": "系列賽戰成 %d 平手",
    "12344": "標準",
    "12592": "目前沒有進行中的投球",
    "13570": "您提交了以下合約金額",
    "16115": "Roboto 標準 (OOTP 18",
    "16157": "無法前往成績看板",
    "16524": "這個聯盟不適用一般的高中／大學規則",
    "18332": "wRC",
    "19684": "有限專員可以執行模擬與處理交易，但不能使用設定或編輯器",
    "23497": "由於違反使用條款，您使用卡片商店的權限已暫時受限",
    "7960": "OOTP Developments",
    "16980": "佈局",                                 # SU = setup man 的欄位縮寫
    "8210": "變速球品質潛力",                        # changeup 被機翻成「改變」
    "8212": "變速球潛力",
    "8240": "變速球品質",
    "6931": "使用在網路商店買到的金鑰代碼兌換完美積分",
    "13581": "季後賽設定",                           # PLAY_OFF 被當成「播放關閉」
    "17204": "Out of the Park Baseball 手冊",
    "17851": "並攻下 %s 分",                          # runs 是得分，不是「執行」
}

# TEAM_NAMES / TEAM_NICKNAMES 整體還沒中文化，這裡只補舊檔殘留的簡體字。
OVERRIDES_TEAM = {
    "21658": "韓華鷹",              # 舊檔寫成「韓华鹰隊」
}

# 佔位符（%player、{nl}…）被機翻吃掉或翻成中文的，遊戲跑起來會直接顯示錯字或
# 少掉一段資訊。這裡照 <EN> 把佔位符補回去。
OVERRIDES_PH = {
    "95": "聯盟官員剛剛公佈了今年可以簽下職業合約的國際球員名單。這些球員不能簽"
          "大聯盟合約，只能拿到含簽約金的小聯盟合約。{nl}{nl}球員名單現在可以在"
          "聯盟選單／交易區找到。{nl}{nl}今年以下這幾位應該最受各隊關注",
    "296": "%inn 局後",
    "2288": "%teanname 贏得系列賽，%number1 比 %number2",
    "2289": "%teanname 系列賽領先，%number1 比 %number2",
    "2344": "%d 公尺",
    "2453": "%a 保送",
    "2595": "簽下第 %round 輪選秀權 %num_pick，簽約金 %bonus，另簽 %num_years 年、"
            "總值 %cache_amount 的大聯盟合約",
    "2654": "我給你的目標是在 %d 之前打進季後賽，我的期限還沒到",
    "2754": "%tournament 的名單尚未選定，%team 的名單無效。請先確定名單再繼續",
    "3083": "您的總教練可以決定是否僱用 %position",
    "3788": "%number1 次 %league 季後賽，%number2 座 %championship 冠軍",
    "3792": "SP: %letter %playername",
    "4130": "桌面尺寸：%d x %d",
    "4674": "有 %nskipped 份延長合約談不攏，必須個別再談",
    "5049": "%player 對 %team 打出 %d1-%d2，%d3 場的連續安打紀錄就此中止",
    "5340": "%bf 人次",
    "5675": "%playername 的救援成功數在 %league 排名第 %number，共 %nums 次",
    "5677": "%playername 的三振數在 %league 排名第 %number，共 %numk 次",
    "5681": "投球局數排名第 %number，共 %numip 局",
    "6226": "%d 公尺",
    "6408": "專員辦公室通知您，%player 拒絕了合格報價，他將成為自由球員",
    "6409": "專員辦公室通知您，%player 拒絕仲裁，他將成為自由球員",
    "7602": "早安 %h，{nl}我一直在關注獨立聯盟，發現一位可能為球隊帶來價值的球員："
            "%o %p。{nl}{nl}%r您有 14 天可以簽下他，之後他就能與其他球隊簽約。該球員"
            "已加入您的候補名單。{nl}{nl}問候，{nl}%c",
    "7823": "與 %teamname 一起贏得 %year 年 %association %championship",
    "9010": "我不覺得這還有什麼好爭的，這是史上集結過最強的一支球隊。從我訂下這個"
            "目標以來拿了 %number1 勝，過去 %year 年間又拿下 %number1 座冠軍，這支"
            "球隊的成就讓我目瞪口呆",
    "9106": "%c 這個項目，哪位 %a投手的生涯成績領先 %l",
    "9538": "%player 被禁賽 %n 場",
    "9688": "錯誤：無法將線上聯盟狀態報告上傳到 %path。%error",
    "9811": "風：%direction，%speed mph",
    "9812": "風：%direction，%speed km/h",
    "9868": "風 %direction %speed mph",
    "9869": "風 %direction %speed km/h",
    "9898": "%win 勝，%playoff 季後賽",
    "9989": "這支球隊的成就讓我非常興奮。過去 %year 年拿下 %win 座 %championship，"
            "足以讓這支球隊躋身史上最偉大之列。談到 %number1-%number2 的 %teamname，"
            "唯一的問題只剩下：這是一支偉大的球隊，還是最偉大的球隊",
    "10018": "錯誤：無法從伺服器匯入球隊 %teamname。%error",
    "10264": "限量版 - 第 %number 張，共 %total 張",
    "10389": "左外野邊線：%n 公尺（牆高 %w 公尺",
    "10390": "左外野：%n 公尺（牆高 %w 公尺",
    "10391": "左中外野：%n 公尺（牆高 %w 公尺",
    "10392": "中外野：%n 公尺（牆高 %w 公尺",
    "10393": "右中外野：%n 公尺（牆高 %w 公尺",
    "10394": "右外野：%n 公尺（牆高 %w 公尺",
    "10395": "右外野邊線：%n 公尺（牆高 %w 公尺",
    "10403": "註記 %d",
    "11280": "除錯資訊；桌面尺寸：%d x %d",
    "11719": "%m,(nl)(nl)您剛從球隊老闆 %o 得知，最新研究顯示 %team 的市場規模已降至"
             "「%market_size",
    "11720": "%m,(nl)(nl)您剛從球隊老闆 %o 得知，最新研究顯示 %team 的市場規模已增加到"
             "「%market_size",
    "11768": "您剛從球隊訓練員得知，%name 的 %injury 在復原過程中出現反覆",
    "11801": "看您現在和過去的成績，我對您的整體表現感到 %mood。場上和董事會的成功"
             "一樣重要，而您看起來正走在這條路上",
    "11807": "我對您的表現仍然感到 %mood，但希望這支球隊能拿出更多東西",
    "11901": "自 %nation 與 %organization 簽下小聯盟合約（簽約金 %money）",
    "11902": "與 %organization 簽下小聯盟合約（簽約金 %money）",
    "11908": "%y 年 %a 得主",
    "11914": "%a 歲的 %p",
    "11999": "%nick_name 身為 %league_name 球隊的 %num_years 年間，共 %num_made 次"
             "打進季後賽。這次是球隊連續第 %num_str_missed 次無緣季後賽，上次打進"
             "季後賽是在 %year_last",
    "12569": "%playename 以 %numberd 支二壘安打追平 %gametype 比賽紀錄",
    "12574": "%playername 以 %numberhr 支全壘打追平 %gametype 比賽紀錄",
    "12651": "二壘跑者搶進三壘，安全上壘，球傳向後面的跑者，出局！_t_",
    "12689": "%n 以 %a 締造 %l 生涯 %c 的歷史紀錄！(nl)恭喜 %f！了不起的成就",
    "12690": "%n 以 %a 追平 %o，(nl)並列單一 %s 第 %p 多的 %c",
    "12693": "%n 的生涯 %c 已經是 %l 史上第 %p 多(nl)，累積 %a！(nl)他的生涯已經"
             "相當精彩",
    "13795": "除錯資訊; get_window_width(): %d x %d",
    "14162": "您今天還可以進行 %n 次 %m 商店嘗試",
    "14334": "%year：%pct%",
    "15871": "%coach (%job - %rating",
    "15961": "%playername (%teamname) 的 %bodypart 受了 %degree 傷勢，診斷尚未完成，"
             "預計未來幾天會有結果",
    "16003": "%team 的正式名單球員人數不合規定！(%nplayers",
    "16417": "LE (%number/%total",
    "16478": "剩餘比賽總數：%total（主場 %home 場，客場 %away 場",
    "17463": "%position 的 %award",
    "17683": "衛冕 %a 得主",
    "18234": "get_window_width(): %d x %d",
    "18361": "他在 %sl 以 %a %c 排名第 %p",
    "18762": "nl)我對你完成我交付目標的表現感到 %mood",
    "18792": "nl)在我們共事的期間，我對你朝著我設定的目標前進的進度一直感到 %mood",
    "19654": "會先搜尋該球場的專屬資料夾，接著才是一般聲音資料夾。檔案的使用順序為："
             "{nl}-BBRef ID/Historical Minors ID%bbr{nl}-Full Name (%fn){nl}"
             "-Short Name (%sn){nl}-Player ID (%pid",
    "22968": "發生錯誤，無法取得卡片商店資料。{nl}請再試一次。如果錯誤仍然存在，"
             "請嘗試重新啟動 OOTP",
    "22969": "發生錯誤，無法建立買單。{nl}請確認您有足夠的完美積分再試一次。如果"
             "錯誤仍然存在，請嘗試重新啟動 OOTP",
    "23026": "建立賣單是為了在市場上賣卡。賣方掛出價格，以最低價優先成交。當另一位"
             "使用者掛出的買單價格等於或高於目前最低掛價時就會成交。卡片會以最低價"
             "賣出；若同一價格有多筆掛單，最早掛出的先成交。{nl}{nl}以賣單掛出的"
             "球員卡會自動從名單中移除並停用。若取消掛單，需要到收藏畫面重新啟用該卡",
    "23062": "發生錯誤，無法建立賣單。{nl}請確認您有足夠的完美積分再試一次。如果"
             "錯誤仍然存在，請嘗試重新啟動 OOTP",
    "14557": "在這裡可以找到 %teamname 組織裡的年輕國際球員，他們是被首席球探"
             "發掘、或從國際業餘新秀庫簽下來的。國際訓練中心的球員人數上限為 "
             "%number，年滿 20 歲的球員會在聯盟公佈年度國際業餘新秀庫之前自動"
             "升上您的預備名單。國際訓練中心滿員時，您的球探就不會再發掘新人。"
             "{nl}{nl}要把球員升上來，請在球員上按右鍵並使用動作選單（總教練"
             "模式下無法使用）。國際訓練中心的球員不能交易",
    "23131": "%league 選秀抽籤結果公佈",
    "23218": "完美球隊宇宙中目前有 %nl 個聯盟、%nt 支球隊。您的 %t 正在 %n 出賽，"
             "屬於 %l 聯盟。季後賽結束後（通常在週日晚上），伺服器會決定哪些球隊"
             "晉級（先看季後賽成績，再看勝率）或降級（勝率最低者）。以您目前的層級，"
             "%p 支球隊晉級、%r 支球隊降級。{nl}{nl}新賽季於美國東部時間週一上午 "
             "10 點開始，新的聯盟檔案通常會提前 2 小時開放下載。祝你好運",
    "23219": "您的 %t 目前在 %n 出賽，這是參賽池層級的聯盟。{nl}{nl}在參賽池期間，"
             "您的球隊會在正常模擬時段內每 30 分鐘與另一位隨機選出的使用者對戰",
    "23396": "發生錯誤，無法取得排名列表。{nl}請再試一次。如果錯誤仍然存在，請嘗試"
             "重新啟動 OOTP",
}


OVERRIDES = {}
OVERRIDES.update(OVERRIDES_TEAM)
OVERRIDES.update(OVERRIDES_LEAGUE)
OVERRIDES.update(OVERRIDES_HCS)
OVERRIDES.update(OVERRIDES_PH)


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


# ---------------------------------------------------------------------------
# 用詞統一。<CN> 是中國大陸的機翻，s2tw 只換字不換詞，所以「設置／文件／激活」
# 這類詞還留著；這裡照順序做取代，把整份檔案的用語拉到同一套。
#
# 順序有意義：長詞要排在短詞前面，否則會被短詞先吃掉（用戶名 -> 使用者名稱 要
# 排在 用戶 -> 使用者 之前）。棒球術語一律跟 text/korean.xml 對齊：
# league = 聯盟、trade = 交易、manager = 總教練、tie = 平手、waiver = 讓渡。
# ---------------------------------------------------------------------------
TERM_FIXES = [
    # 介面與電腦用語
    ("用戶名", "使用者名稱"),
    ("用戶", "使用者"),
    ("文件夾", "資料夾"),
    ("文本文件", "文字檔"),
    ("文本框", "文字方塊"),
    ("文本", "文字"),
    ("文件", "檔案"),
    ("數據庫", "資料庫"),
    ("磁盤", "磁碟"),
    ("應用程序", "應用程式"),
    ("調度程序", "排程器"),
    ("驅動程序", "驅動程式"),
    ("顯卡", "顯示卡"),
    ("快捷方式", "捷徑"),
    ("設置", "設定"),
    ("激活", "啟用"),
    ("單擊", "點擊"),
    ("登錄", "登入"),
    ("注銷", "登出"),
    ("搜索", "搜尋"),
    ("質量", "品質"),
    ("調試", "除錯"),
    ("對話框", "對話視窗"),
    ("計算機", "電腦"),
    ("粘貼", "貼上"),
    ("緩存", "快取"),
    ("網絡", "網路"),
    ("內存", "記憶體"),
    ("人工智能", "人工智慧"),
    ("智能", "智慧"),
    ("首選項", "偏好設定"),
    ("端口", "連接埠"),
    ("視頻", "影片"),
    ("加載", "載入"),
    ("線程", "執行緒"),
    ("操作系統", "作業系統"),
    ("菜單", "選單"),
    ("異步", "非同步"),
    ("圖標欄", "圖示列"),
    ("圖標", "圖示"),
    ("上載", "上傳"),
    ("全屏", "全螢幕"),
    ("屏幕", "螢幕"),
    ("分辨率", "解析度"),
    ("添加", "新增"),
    ("保存", "儲存"),
    ("存儲", "儲存"),
    ("全局", "全域"),
    (r"在線(?!上)", "線上"),
    ("互聯網", "網際網路"),
    ("打開", "開啟"),
    ("運行", "執行"),
    ("自定義", "自訂"),
    ("剪貼板", "剪貼簿"),
    ("字符串", "字串"),
    ("嚮導", "精靈"),
    ("跟蹤", "追蹤"),
    ("模板", "範本"),
    ("界面", "介面"),
    ("獲取", "取得"),
    ("刷新", "重新整理"),
    ("支持", "支援"),
    ("附加組件", "附加元件"),
    ("插件", "外掛"),
    ("滾動", "捲動"),
    ("窗口", "視窗"),
    ("複選框", "核取方塊"),
    ("工具欄", "工具列"),
    ("任務欄", "工作列"),
    ("控件", "控制項"),
    ("代碼", "程式碼"),
    (r"解壓(?!縮)", "解壓縮"),
    ("賬戶", "帳戶"),
    ("賬號", "帳號"),
    ("鏈接", "連結"),
    ("密鑰", "金鑰"),
    ("收藏夾", "收藏"),
    ("實時", "即時"),
    ("圖像", "影像"),
    ("車間", "創意工坊"),
    ("後臺", "背景"),
    ("模擬人生", "模擬"),
    (r"佈局(?!投手)", "版面"),   # setup man 的「佈局投手」不能動
    ("高亮", "精彩片段"),
    ("峯值", "巔峰"),
    ("注意力！", "注意！"),
    (r"(?<!球)隊列", "佇列"),    # 「球隊列表」不是佇列
    ("條目池", "參賽池"),

    # 棒球與遊戲術語
    ("貿易", "交易"),
    ("花名冊", "名單"),
    ("聯賽", "聯盟"),
    ("經理人", "總教練"),
    (r"(?<!總)經理", "總教練"),
    ("人工管理人員", "人類總教練"),
    ("管理器", "總教練"),
    ("上帝模式", "專員模式"),
    ("委員會", "專員"),
    ("合同", "合約"),
    ("平局", "平手"),
    ("賽區", "分區"),
    ("公園", "球場"),
    ("棄權", "讓渡"),
    ("包裝", "卡包"),
    ("偵察", "球探"),
    ("對象", "物件"),
    ("設備", "裝置"),
    ("性能", "效能"),
    ("崩潰", "當機"),
    ("父母聯盟", "母聯盟"),
    ("單打擊員", "點擊球員"),      # 舊檔錯字，原意是「右鍵點擊球員姓名」

    # s2tw 沒換到位的異體字，一律用教育部的寫法
    ("啓", "啟"),
    ("裏", "裡"),
    ("爲", "為"),
    ("着", "著"),
    ("麪", "面"),
    ("籤約", "簽約"),
    ("幹得", "做得"),
    ("幹擾", "干擾"),
]
TERM_FIXES = [(re.compile(p), r) for p, r in TERM_FIXES]

# 同一個詞在不同英文原句裡要翻成不同的中文，只能看 <EN> 決定。
def _pick_info(en):
    return "訊息" if "message" in en else "資訊"


def _pick_news(en):
    return "消息" if "news" in en else "訊息"


def _pick_data(en):
    # 球員成績叫「數據」，其餘的 data 是「資料」
    return "數據" if "stat" in en else "資料"


def _pick_visit(en):
    return "造訪" if "visit" in en else "進入"


def _pick_regular(en):
    if "routine" in en:
        return "例行"
    if "regular season" in en or "post-season" in en or "postseason" in en:
        return "例行賽"
    return "一般"


def _pick_program(en):
    # program / app 才是「程式」，其餘的 procedure 保留「程序」
    return "程式" if ("program" in en or "app" in en or "software" in en) else "程序"


def _pick_profile(en):
    return "個人資料" if "profile" in en else "設定檔"


def _make_waiver(word):
    # waiver 一律叫「讓渡」，release 才是「釋出」。舊檔兩者混用，看 <EN> 拆開。
    def pick(en):
        return "讓渡" if "waiver" in en else word
    return pick


EN_TERM_FIXES = [
    (re.compile("信息"), _pick_info),
    (re.compile("消息"), _pick_news),
    (re.compile("數據"), _pick_data),
    (re.compile("訪問"), _pick_visit),
    (re.compile("常規"), _pick_regular),
    (re.compile("程序"), _pick_program),
    (re.compile("配置檔案"), _pick_profile),
    (re.compile("釋出"), _make_waiver("釋出")),
    (re.compile("豁免"), _make_waiver("豁免")),
    (re.compile("放棄"), _make_waiver("放棄")),
]

# 前面幾輪取代完才會冒出來的疊字，最後再掃一次
POST_FIXES = [
    ("{nl }", "{nl}"),          # 機翻把換行標記中間插了空白，遊戲會照字面印出來
    ("{ nl}", "{nl}"),
    ("資料資料夾", "資料夾"),   # application data folder，兩個「資料」很拗口
    ("個人資料資料", "個人資料"),
]

TERM_SKIP_SECTIONS = TEAM_SECTIONS | {"TEAM_ABBR"}


def apply_terms(section, en, value):
    """把用詞統一套到一筆 <KR> 上。球隊名稱與英文縮寫不動。"""
    if section in TERM_SKIP_SECTIONS:
        return value
    for pat, repl in TERM_FIXES:
        value = pat.sub(repl, value)
    en = en.lower()
    for pat, pick in EN_TERM_FIXES:
        value = pat.sub(pick(en), value)
    for a, b in POST_FIXES:
        value = value.replace(a, b)
    return value


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


PLACEHOLDER_RE = re.compile(r"%[A-Za-z_][A-Za-z0-9_]*|%\d*[dscfn]\b|\{nl\}")


def placeholders_match(en, kr):
    """<KR> 的佔位符要跟 <EN> 一樣多、一樣是那幾個。

    英文那邊有些是 %r / %a 直接黏著後面的字（%rstarting、%apitchers），切不開，
    所以中文的佔位符只要是英文那一個的開頭就算對得上。
    """
    want, got = sorted(PLACEHOLDER_RE.findall(en)), PLACEHOLDER_RE.findall(kr)
    if sorted(got) == want:
        return True
    rest = list(got)
    for token in want:
        hit = next((g for g in rest if token.startswith(g)), None)
        if hit is None:
            return False
        rest.remove(hit)
    return not rest


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
    stats = dict(team=0, override=0, kept=0, from_cn=0, from_en=0, untouched=0,
                 terms=0)

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
                # 沒有新值，但既有的中文一樣要跑用詞統一
                new = cur
                stats["untouched"] += 1

            fixed = apply_terms(section, html.unescape(tag_value(body, "EN") or ""),
                                new)
            if fixed != new:
                stats["terms"] += 1
            new = fixed

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
    print(f"  其中被用詞統一改到  : {stats['terms']}")


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
        expect = apply_terms(D[i][0], html.unescape(f["EN"] or ""), kr)
        if i not in O or O[i][1]["KR"] != expect:
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

    # 佔位符掉了或被翻成中文（「%球員」「% 職位」），遊戲會直接把錯字印在畫面上
    bad_ph = []
    for i, (sec, f) in O.items():
        if sec != "HARD_CODED_STRINGS" or f["KR"] is None:
            continue
        en, kr = html.unescape(f["EN"] or ""), html.unescape(f["KR"])
        if not placeholders_match(en, kr):
            bad_ph.append(i)
    print(f"  佔位符與英文對不上    : {len(bad_ph)}", bad_ph[:5] if bad_ph else "")
    ok = ok and not bad_ph

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
