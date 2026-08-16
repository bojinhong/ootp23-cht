#!/usr/bin/env python3
"""以 temp/schools.xml 為基底，合併 database/schools.xml 既有的中文翻譯。

合併規則（每筆 SCHOOL 以 id 對應）：

  1. 英文欄位（CITY / STATE_ABBR / NAME / NICK / ASSO / CONF）與 SCHOOL 屬性
     一律沿用 temp，不做任何改動。
  2. 四個 *_KOREAN 欄位：
     - 舊檔該欄位含中日文字 -> 視為人工翻譯，保留舊檔的值。
     - 否則 -> 填入 temp 的對應英文欄位（英文為空時即為空）。

規則 2 的第二條就是本專案既有的做法：韓文欄位不留韓文，沒有中文翻譯時退回英文。
拿舊檔驗證過，這條規則能重現 20,851 筆未受英文欄位變動影響的記錄，
僅 87 筆原本留空的欄位會改為填入英文（比留白好）。

用法:
    python3 tools/merge_schools.py                          # temp + database -> database
    python3 tools/merge_schools.py BASE.xml OLD.xml OUT.xml

刻意採用逐行字串取代而非 XML 重新序列化，理由同 localize_names.py：
原檔排版與實體跳脫必須原封不動。
"""

import html
import os
import re
import sys

# 英文欄位 -> 韓文欄位。順序與檔案中出現的順序一致（英文全部在韓文之前）。
PAIRS = [
    ("NAME", "NAME_KOREAN"),
    ("NICK", "NICK_KOREAN"),
    ("ASSO", "ASSO_KOREAN"),
    ("CONF", "CONF_KOREAN"),
]
ENG_TAGS = [eng for eng, _ in PAIRS]
KOR_TAGS = {kor: eng for eng, kor in PAIRS}

CJK_RE = re.compile(r"[一-鿿぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
SCHOOL_ID_RE = re.compile(r'<SCHOOL\s[^>]*\bid="(\d+)"')
FIELD_RE = re.compile(r"<(\w+)>(.*)</\1>")

DEFAULT_BASE = "temp/schools.xml"
DEFAULT_OLD = "database/schools.xml"
DEFAULT_OUT = "database/schools.xml"


def load_translations(path):
    """從舊檔撈出所有含中日文的 *_KOREAN 值，key 為 (school_id, tag)。"""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()

    out = {}
    for m in re.finditer(r"<SCHOOL ([^>]*)>(.*?)</SCHOOL>", text, re.S):
        sid = re.search(r'id="(\d+)"', m.group(1)).group(1)
        for tag, raw in re.findall(r"<(\w+)>(.*?)</\1>", m.group(2), re.S):
            if tag in KOR_TAGS and CJK_RE.search(html.unescape(raw)):
                out[(sid, tag)] = raw
    return out


def merge(base, old, out_path):
    translations = load_translations(old)

    kept = 0
    from_english = 0
    blanked = 0
    sid = None
    english = {}

    tmp = out_path + ".tmp"
    with open(base, encoding="utf-8", newline="") as fin, \
         open(tmp, "w", encoding="utf-8", newline="") as fout:
        for line in fin:
            m = SCHOOL_ID_RE.search(line)
            if m:
                sid = m.group(1)
                english = {}
                fout.write(line)
                continue

            field = FIELD_RE.search(line)
            if field is None:
                fout.write(line)
                continue

            tag, raw = field.group(1), field.group(2)

            if tag in ENG_TAGS:
                english[tag] = raw
                fout.write(line)
                continue

            if tag not in KOR_TAGS:
                fout.write(line)
                continue

            key = (sid, tag)
            if key in translations:
                new_raw = translations[key]
                kept += 1
            else:
                new_raw = english.get(KOR_TAGS[tag], "")
                if new_raw:
                    from_english += 1
                else:
                    blanked += 1

            fout.write(line.replace(
                f"<{tag}>{raw}</{tag}>", f"<{tag}>{new_raw}</{tag}>", 1))

    os.replace(tmp, out_path)

    print(f"基底 {base} + 翻譯 {old} -> {out_path}")
    print(f"  舊檔可用的中文翻譯 : {len(translations)}")
    print(f"  保留中文翻譯       : {kept}")
    print(f"  退回英文           : {from_english}")
    print(f"  留空(英文亦為空)   : {blanked}")
    return kept, len(translations)


def verify(out_path, base, old):
    with open(out_path, encoding="utf-8-sig") as f:
        out_text = f.read()

    def parse(path):
        with open(path, encoding="utf-8-sig") as f:
            s = f.read()
        rec = {}
        for m in re.finditer(r"<SCHOOL ([^>]*)>(.*?)</SCHOOL>", s, re.S):
            sid = re.search(r'id="(\d+)"', m.group(1)).group(1)
            rec[sid] = (m.group(1),
                        dict(re.findall(r"<(\w+)>(.*?)</\1>", m.group(2), re.S)))
        return rec

    O = parse(out_path)
    B = parse(base)
    D = parse(old)
    u = html.unescape
    ok = True

    print(f"檢查 {out_path}")
    print(f"  記錄數                : {len(O)}")
    if set(O) != set(B):
        print(f"  id 集合與基底不符!")
        ok = False

    hangul = len(HANGUL_RE.findall(out_text))
    print(f"  殘留韓文字元          : {hangul}")
    ok = ok and hangul == 0

    # 英文欄位與 SCHOOL 屬性必須與基底完全相同
    eng_diff = attr_diff = 0
    for sid in O:
        if sid not in B:
            continue
        if O[sid][0] != B[sid][0]:
            attr_diff += 1
        for tag in ["CITY", "STATE_ABBR"] + ENG_TAGS:
            if O[sid][1].get(tag) != B[sid][1].get(tag):
                eng_diff += 1
    print(f"  英文欄位偏離基底      : {eng_diff}")
    print(f"  SCHOOL 屬性偏離基底   : {attr_diff}")
    ok = ok and eng_diff == 0 and attr_diff == 0

    # 舊檔的中文翻譯必須全數保留
    lost = []
    for sid, (_, fields) in D.items():
        for tag in KOR_TAGS:
            v = fields.get(tag, "")
            if CJK_RE.search(u(v)) and sid in O and u(O[sid][1].get(tag, "")) != u(v):
                lost.append((sid, tag))
    print(f"  遺失的中文翻譯        : {len(lost)}", lost[:5] if lost else "")
    ok = ok and not lost

    # 沒有中文翻譯的欄位必須等於基底的英文欄位
    bad = 0
    for sid in O:
        if sid not in B:
            continue
        for eng, kor in PAIRS:
            v = O[sid][1].get(kor, "")
            if CJK_RE.search(u(v)):
                continue
            if u(v) != u(B[sid][1].get(eng, "")):
                bad += 1
    print(f"  非中文欄位 != 英文    : {bad}")
    ok = ok and bad == 0

    print("  結果                  : " + ("PASS" if ok else "FAIL"))
    return ok


def main(argv):
    base = argv[0] if len(argv) > 0 else DEFAULT_BASE
    old = argv[1] if len(argv) > 1 else DEFAULT_OLD
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT

    # 輸出會蓋掉舊檔時，先把舊檔內容讀進記憶體再寫
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
