#!/usr/bin/env python3
"""以官方原始檔為基底，重建 text/gui_translations.xml 的 <KR> 中文翻譯。

合併規則（每筆以 HCS 的 i 屬性對應，只動 <KR>）：

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


def load_opencc():
    try:
        from opencc import OpenCC
    except ImportError:
        sys.exit("需要 opencc，請先執行: pip install opencc-python-reimplemented")
    return OpenCC(OPENCC_CONFIG).convert


def simplified_only_chars():
    """只存在於簡體的字（自己不在自己的繁體候選裡），拿來檢查有沒有漏轉。"""
    import opencc
    path = os.path.join(os.path.dirname(opencc.__file__),
                        "dictionary", "STCharacters.txt")
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            s, t = line.rstrip("\n").split("\t")
            if s not in t.split(" "):
                out.add(s)
    return out


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
    stats = dict(override=0, kept=0, from_cn=0, from_en=0, untouched=0)

    def fix_section(sm):
        section = sm.group("sec")

        def fix_hcs(m):
            i, body = m.group("i"), m.group("body")
            cur = tag_value(body, "KR")
            if cur is None:
                return m.group(0)
            cn = tag_value(body, "CN") or ""

            if i in OVERRIDES:
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
        if (i in OVERRIDES or kr is None or kr == f["CN"]
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
        mark = "" if sec in CN_FILL_SECTIONS else "  (待人工翻譯)"
        print(f"  {sec:20s} 殘留韓文 {len(han):4d} / 殘留簡體 {len(sim):3d}{mark}")
        if sec in CN_FILL_SECTIONS:
            if han:
                print("      韓文:", han[:5])
            if sim:
                print("      簡體:", sim[:5])
            ok = ok and not han and not sim

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
