#!/usr/bin/env python3
"""以官方原始檔為基底重建 text/korean.xml，並把每個分類精簡成一種敘述。

遊戲的逐球播報現在有視覺化呈現，同一個情境不需要幾十種講法。這支程式每個
<CAT> 只留一筆 <OBJ> 上線，其餘一律「註解掉」而不是刪掉，之後想換講法或是
要補翻譯，把註解拆開就能用。

保留規則（以 <CAT> 為單位）：

  1. 該分類有不帶 <COND> 的 OBJ -> 只留一筆，其餘全部註解。
  2. 整個分類的 OBJ 都帶 <COND> -> 每一種條件組合各留一筆。
     這種分類的條件是帶語意的（季後賽領先/落後/平手、守備等級 1~20、
     教練風格…），collapse 成一句會變成講錯話，所以不能只留一筆。

同一組裡留哪一筆，依序看：已經有中文的 > 不帶 <COND> 的 > 沒有使用次數限制的。

留下來的那筆會把 usage_chance_for_game / only_once_per_x1 / only_once_per_x2
拿掉——整個分類只剩這一句了，再限制它一場只能用一次會沒台詞可播。

中文從舊檔以 OBJ id 對應搬過來，連「已經被註解掉」的也會撿回來，所以翻譯不會
因為某次精簡而消失。基底裡有、舊檔沒有中文的就維持英文。

XML 的註解不能包含 "--"，而內文裡的破折號正是寫成 "--"。被註解起來的那些
OBJ 會在連續的 - 之間補空白（只影響註解內容，上線的那筆不會被動到）。

用法:
    python3 tools/merge_korean.py                     # temp + text -> text
    python3 tools/merge_korean.py BASE.xml OLD.xml OUT.xml
    python3 tools/merge_korean.py --verify            # 只檢查不寫檔
    python3 tools/merge_korean.py --todo              # 列出還沒翻的，寫到 stdout

沒有 temp/english.xml 時會拿 text/korean.xml 自己當基底。
"""

import html
import os
import re
import shutil
import sys

DEFAULT_BASE = "temp/english.xml"
FALLBACK_BASE = "text/korean.xml"
DEFAULT_OLD = "text/korean.xml"
DEFAULT_OUT = "text/korean.xml"

CJK_RE = re.compile(r"[一-鿿]")
CAT_SPLIT_RE = re.compile(r'(?=<CAT id=")')
CAT_ID_RE = re.compile(r'<CAT id="(\d+)"')
OBJ_RE = re.compile(r"<OBJ [^>]*?(?:/>|>.*?</OBJ>)", re.S)
OBJ_ID_RE = re.compile(r'<OBJ id="(\d+)"')
COND_RE = re.compile(r'<COND id="(\d+)" value="([^"]*)"')
TEXT_ATTR_RE = re.compile(r'text="([^"]*)"')
TXT_TAG_RE = re.compile(r"<TXT>(.*?)</TXT>", re.S)
LIMIT_ATTR_RE = re.compile(r'\s(?:usage_chance_for_game|only_once_per_x[12])="[^"]*"')
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def obj_text(block):
    """回傳 (raw_text, kind)，kind 是 'attr' 或 'tag'；沒有文字回傳 (None, None)。"""
    m = TEXT_ATTR_RE.search(block)
    if m:
        return m.group(1), "attr"
    m = TXT_TAG_RE.search(block)
    if m:
        return m.group(1), "tag"
    return None, None


def set_obj_text(block, new):
    t, kind = obj_text(block)
    if t is None or new == t:
        return block
    if kind == "attr":
        return block.replace(f'text="{t}"', f'text="{new}"', 1)
    return block.replace(f"<TXT>{t}</TXT>", f"<TXT>{new}</TXT>", 1)


def cond_sig(block):
    return tuple(sorted(COND_RE.findall(block)))


def load_translations(path):
    """舊檔所有含中文的 OBJ（含被註解掉的），id -> 原始字串。"""
    out = {}
    for block in OBJ_RE.findall(read(path)):
        t, _ = obj_text(block)
        if t is not None and CJK_RE.search(html.unescape(t)):
            out[OBJ_ID_RE.match(block).group(1)] = t
    return out


def pick(blocks, translations):
    """一組候選裡挑要留下來的那筆。"""
    def rank(b):
        return (OBJ_ID_RE.match(b).group(1) in translations,
                "<COND" not in b,
                not LIMIT_ATTR_RE.search(b))
    return max(blocks, key=rank)



def comment_out(chunk):
    """把一段 OBJ 包成 XML 註解。XML 註解不能出現連續兩個 -，所以每個後面還跟著
    - 的 - 都補一個空白（--- 這種連三個的也要處理，單純 replace 會漏掉）。"""
    return "<!--" + re.sub(r"-(?=-)", "- ", chunk) + "-->"


def rebuild(base, translations, stats):
    parts = CAT_SPLIT_RE.split(base)
    head, cats = parts[0], parts[1:]
    out = [head]

    for cat in cats:
        blocks = [b for b in OBJ_RE.findall(cat) if obj_text(b)[0] is not None]
        if not blocks:
            out.append(cat)
            continue

        unconditional = [b for b in blocks if not cond_sig(b)]
        if unconditional:
            keep = {OBJ_ID_RE.match(pick(unconditional, translations)).group(1)}
            stats["cat_single"] += 1
        else:
            groups = {}
            for b in blocks:
                groups.setdefault(cond_sig(b), []).append(b)
            keep = {OBJ_ID_RE.match(pick(g, translations)).group(1)
                    for g in groups.values()}
            stats["cat_by_cond"] += 1

        # 逐塊重組：保留的原樣輸出（去掉使用次數限制、填中文），
        # 其餘連同前面的空白一起累積起來，遇到保留的才收成一個註解。
        # <CAT ...> 開頭那一段要先吐出來，不然會被捲進第一個註解裡
        first = OBJ_RE.search(cat)
        new_cat, cursor, pending = [cat[:first.start()]], first.start(), ""
        for m in OBJ_RE.finditer(cat):
            block = m.group(0)
            if obj_text(block)[0] is None:
                continue
            gap = cat[cursor:m.start()]
            cursor = m.end()
            if OBJ_ID_RE.match(block).group(1) in keep:
                if pending:
                    new_cat.append(comment_out(pending))
                    pending = ""
                new_cat.append(gap)
                block = LIMIT_ATTR_RE.sub("", block)
                zh = translations.get(OBJ_ID_RE.match(block).group(1))
                if zh is not None:
                    block = set_obj_text(block, zh)
                    stats["translated"] += 1
                else:
                    stats["still_english"] += 1
                new_cat.append(block)
                stats["kept"] += 1
            else:
                # 被註解起來的也要填中文：舊檔既有的翻譯不能因為這次沒被選中
                # 就被英文蓋掉，之後想換講法時拆開註解就能直接用。
                zh = translations.get(OBJ_ID_RE.match(block).group(1))
                if zh is not None:
                    block = set_obj_text(block, zh)
                    stats["commented_zh"] += 1
                pending += gap + block
                stats["commented"] += 1
        if pending:
            new_cat.append(comment_out(pending))
        new_cat.append(cat[cursor:])
        out.append("".join(new_cat))

    return "".join(out)


def merge(base_path, old_path, out_path):
    translations = load_translations(old_path)
    stats = dict(cat_single=0, cat_by_cond=0, kept=0, commented=0,
                 commented_zh=0, translated=0, still_english=0)
    result = rebuild(read(base_path), translations, stats)

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(result)
    os.replace(tmp, out_path)

    print(f"基底 {base_path} + 翻譯 {old_path} -> {out_path}")
    print(f"  舊檔可用的中文       : {len(translations)}")
    print(f"  只留一筆的分類       : {stats['cat_single']}")
    print(f"  依條件各留一筆的分類 : {stats['cat_by_cond']}")
    print(f"  上線的 OBJ           : {stats['kept']}")
    print(f"    其中已是中文       : {stats['translated']}")
    print(f"    還是英文待翻       : {stats['still_english']}")
    print(f"  註解起來的 OBJ       : {stats['commented']}")
    print(f"    其中保住的中文     : {stats['commented_zh']}")


def verify(out_path, base_path):
    import xml.etree.ElementTree as ET
    text = read(out_path)
    ok = True

    print(f"檢查 {out_path}")
    try:
        ET.fromstring(text)
        print("  XML 解析             : OK")
    except ET.ParseError as exc:
        print(f"  XML 解析             : 失敗 {exc}")
        ok = False

    live = COMMENT_RE.sub("", text)
    live_ids = {OBJ_ID_RE.match(b).group(1) for b in OBJ_RE.findall(live)}
    all_ids = {OBJ_ID_RE.match(b).group(1) for b in OBJ_RE.findall(text)}
    base_ids = {OBJ_ID_RE.match(b).group(1) for b in OBJ_RE.findall(read(base_path))}
    print(f"  OBJ 總數             : {len(all_ids)}")
    print(f"  上線 / 註解          : {len(live_ids)} / {len(all_ids) - len(live_ids)}")

    lost = base_ids - all_ids
    print(f"  基底有、輸出沒有的   : {len(lost)}", sorted(lost)[:5] if lost else "")
    ok = ok and not lost

    # 每個有內容的分類都至少要有一筆上線，否則遊戲會沒台詞
    empty = []
    for cat in CAT_SPLIT_RE.split(text)[1:]:
        cid = CAT_ID_RE.match(cat).group(1)
        has = [b for b in OBJ_RE.findall(cat) if obj_text(b)[0] is not None]
        alive = [b for b in OBJ_RE.findall(COMMENT_RE.sub("", cat))
                 if obj_text(b)[0] is not None]
        if has and not alive:
            empty.append(cid)
    print(f"  沒有任何上線敘述的分類: {len(empty)}", empty[:5] if empty else "")
    ok = ok and not empty

    zh = sum(1 for b in OBJ_RE.findall(live)
             if (obj_text(b)[0] or "") and CJK_RE.search(html.unescape(obj_text(b)[0])))
    withtext = sum(1 for b in OBJ_RE.findall(live) if obj_text(b)[0] is not None)
    print(f"  上線敘述中文化進度   : {zh} / {withtext}"
          f"  ({zh * 100 // max(withtext, 1)}%)")

    print("  結果                 : " + ("PASS" if ok else "FAIL"))
    return ok


def todo(out_path):
    """把還沒翻的上線敘述印出來，格式 id<TAB>英文。"""
    live = COMMENT_RE.sub("", read(out_path))
    for cat in CAT_SPLIT_RE.split(live)[1:]:
        cid = CAT_ID_RE.match(cat).group(1)
        for b in OBJ_RE.findall(cat):
            t, _ = obj_text(b)
            if t is None or CJK_RE.search(html.unescape(t)):
                continue
            print(f"{cid}\t{OBJ_ID_RE.match(b).group(1)}\t{t}")


def main(argv):
    mode = None
    for flag in ("--verify", "--todo"):
        if flag in argv:
            mode = flag
            argv = [a for a in argv if a != flag]

    default_base = DEFAULT_BASE if os.path.exists(DEFAULT_BASE) else FALLBACK_BASE
    base = argv[0] if len(argv) > 0 else default_base
    old = argv[1] if len(argv) > 1 else DEFAULT_OLD
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT

    if mode == "--todo":
        todo(out)
        return 0
    if mode == "--verify":
        return 0 if verify(out, base) else 1

    if os.path.abspath(old) == os.path.abspath(out):
        snapshot = out + ".orig.tmp"
        shutil.copyfile(old, snapshot)
        try:
            merge(base if base != old else snapshot, snapshot, out)
            ok = verify(out, base if base != old else snapshot)
        finally:
            os.remove(snapshot)
    else:
        merge(base, old, out)
        ok = verify(out, base)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
