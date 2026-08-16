#!/usr/bin/env python3
"""以 temp/world_default.xml 為基底，合併 database/world_default.xml 既有的中文翻譯。

合併規則（每筆以「元素型別 + id」對應，四組屬性各自套用）：

  1. 舊檔該屬性含中日文字 -> 視為人工翻譯，保留舊檔的值。
  2. 否則基底該屬性是韓文    -> 填入基底的對應英文屬性；該屬性不存在時退而用 name。
  3. 其餘                    -> 原樣保留基底的值。

規則 3 讓 abbr_korean 這種本來就是拉丁字母、但刻意與 abbr 不同的官方資料
（例：STATE 1670 abbr="GUN" abbr_korean="GUM"）不會被無謂覆蓋。

規則 2 的 name 退路是給兩字母地名用的：官方對 name="Pô" 這類城市根本不給 abbr，
只給 abbr_korean="뽀Í"，直接清空會讓韓文版少一個縮寫，改用 name 才貼近英文版的行為。

英文屬性（name / abbr / dem / short）與其餘所有欄位一律沿用基底，不做任何改動。

用法:
    python3 tools/merge_world.py                        # temp + database -> database
    python3 tools/merge_world.py BASE.xml OLD.xml OUT.xml
"""

import html
import os
import re
import sys

PAIRS = [
    ("name", "name_korean"),
    ("abbr", "abbr_korean"),
    ("dem", "dem_korean"),
    ("short", "short_korean"),
]
KOR_TO_ENG = {kor: eng for eng, kor in PAIRS}

ELEMENTS = {"CONTINENT", "NATION", "REGION", "STATE", "CITY", "ETHNICITY"}

CJK_RE = re.compile(r"[一-鿿぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
OPEN_TAG_RE = re.compile(r"<(\w+)\s([^>]*?)/?>")
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

DEFAULT_BASE = "temp/world_default.xml"
DEFAULT_OLD = "database/world_default.xml"
DEFAULT_OUT = "database/world_default.xml"


def load_translations(path):
    """撈出舊檔所有含中日文的 *_korean 值，key 為 (element, id, attr)。"""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()

    out = {}
    for m in OPEN_TAG_RE.finditer(text):
        el = m.group(1)
        if el not in ELEMENTS:
            continue
        attrs = dict(ATTR_RE.findall(m.group(2)))
        eid = attrs.get("id")
        if eid is None:
            continue
        for kor in KOR_TO_ENG:
            v = attrs.get(kor)
            if v is not None and CJK_RE.search(html.unescape(v)):
                out[(el, eid, kor)] = v
    return out


def merge(base, old, out_path):
    translations = load_translations(old)

    kept = from_english = untouched = via_name = no_source = 0

    tmp = out_path + ".tmp"
    with open(base, encoding="utf-8-sig", newline="") as fin, \
         open(tmp, "w", encoding="utf-8", newline="") as fout:
        fout.write("﻿")
        for line in fin:
            m = OPEN_TAG_RE.search(line)
            if m is None or m.group(1) not in ELEMENTS:
                fout.write(line)
                continue

            el = m.group(1)
            attrs = dict(ATTR_RE.findall(m.group(2)))
            eid = attrs.get("id")
            if eid is None:
                fout.write(line)
                continue

            new_line = line
            for kor, eng in KOR_TO_ENG.items():
                cur = attrs.get(kor)
                if cur is None:
                    continue

                key = (el, eid, kor)
                if key in translations:
                    new_val = translations[key]
                    kept += 1
                elif HANGUL_RE.search(html.unescape(cur)):
                    new_val = attrs.get(eng)
                    if new_val is None:
                        new_val = attrs.get("name")
                        if new_val is None:
                            no_source += 1
                            continue
                        via_name += 1
                    from_english += 1
                else:
                    untouched += 1
                    continue

                if new_val != cur:
                    new_line = new_line.replace(
                        f'{kor}="{cur}"', f'{kor}="{new_val}"', 1)

            fout.write(new_line)

    os.replace(tmp, out_path)

    print(f"基底 {base} + 翻譯 {old} -> {out_path}")
    print(f"  舊檔可用的中文翻譯 : {len(translations)}")
    print(f"  保留中文翻譯       : {kept}")
    print(f"  韓文改填英文       : {from_english}")
    print(f"    其中改用 name    : {via_name}")
    print(f"  原樣保留(非韓文)   : {untouched}")
    if no_source:
        print(f"  無來源、維持韓文   : {no_source}")


def parse(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    out = {}
    for m in OPEN_TAG_RE.finditer(text):
        el = m.group(1)
        if el not in ELEMENTS:
            continue
        attrs = dict(ATTR_RE.findall(m.group(2)))
        if "id" in attrs:
            out[(el, attrs["id"])] = attrs
    return out, text


def verify(out_path, base, old):
    O, out_text = parse(out_path)
    B, _ = parse(base)
    D, _ = parse(old)
    u = html.unescape
    ok = True

    print(f"檢查 {out_path}")
    print(f"  元素筆數              : {len(O)}")
    if set(O) != set(B):
        print(f"  元素集合與基底不符! 缺 {len(set(B)-set(O))} 多 {len(set(O)-set(B))}")
        ok = False

    hangul = len(HANGUL_RE.findall(out_text))
    print(f"  殘留韓文字元          : {hangul}")
    ok = ok and hangul == 0

    # 英文屬性與其他所有非 *_korean 屬性必須與基底一致
    drift = 0
    examples = []
    for k in O:
        if k not in B:
            continue
        for a, v in B[k].items():
            if a in KOR_TO_ENG:
                continue
            if O[k].get(a) != v:
                drift += 1
                if len(examples) < 4:
                    examples.append((k, a, v, O[k].get(a)))
    print(f"  非韓文屬性偏離基底    : {drift}", examples if examples else "")
    ok = ok and drift == 0

    # 舊檔的中文翻譯必須全數保留
    lost = []
    for k, attrs in D.items():
        for kor in KOR_TO_ENG:
            v = attrs.get(kor)
            if v is not None and CJK_RE.search(u(v)):
                if k not in O or u(O[k].get(kor, "")) != u(v):
                    lost.append((k, kor))
    print(f"  遺失的中文翻譯        : {len(lost)}", lost[:5] if lost else "")
    ok = ok and not lost

    # 沒有翻譯、基底為韓文的欄位必須等於基底的英文屬性
    bad = 0
    for k in O:
        if k not in B:
            continue
        for eng, kor in PAIRS:
            cur = O[k].get(kor)
            if cur is None or CJK_RE.search(u(cur)):
                continue
            base_val = B[k].get(kor, "")
            if HANGUL_RE.search(u(base_val)):
                expected = B[k].get(eng)
                if expected is None:
                    expected = B[k].get("name", base_val)
                if u(cur) != u(expected):
                    bad += 1
            elif u(cur) != u(base_val):
                bad += 1
    print(f"  回退規則不符          : {bad}")
    ok = ok and bad == 0

    print("  結果                  : " + ("PASS" if ok else "FAIL"))
    return ok


def main(argv):
    base = argv[0] if len(argv) > 0 else DEFAULT_BASE
    old = argv[1] if len(argv) > 1 else DEFAULT_OLD
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT

    if os.path.abspath(old) == os.path.abspath(out):
        import shutil
        snapshot = out + ".orig.tmp"
        shutil.copyfile(old, snapshot)
        try:
            merge(base, snapshot, out)
            ok = verify(out, base, snapshot)
        finally:
            os.remove(snapshot)
    else:
        merge(base, old, out)
        ok = verify(out, base, old)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
