#!/usr/bin/env python3
"""以 temp/tutorial_data.xml 為基底，合併 text/tutorial_data.xml 既有的中文翻譯。

合併規則（每筆以 TI 的 i 屬性對應，<KR> 與 <KRGROUP> 各自套用）：

  1. 舊檔該標籤含中日文字 -> 視為既有翻譯，保留舊檔的值。
  2. 否則基底該標籤是韓文  -> 填入基底的 <EN> / <ENGROUP>。
  3. 其餘                  -> 原樣保留基底的值。

其他標籤（EN / ES / JP / CN 及各自的 GROUP）與 TI 屬性一律沿用基底，不做任何改動。

這個檔案有兩個地方不能用 localize_names.py 那種逐行處理：
  - 有 6 筆標籤的值跨行（<EN> 5 筆、<KR> 1 筆），必須整檔比對。
  - 值裡面藏著 CRLF，讀寫都要 newline="" 才不會被 Python 的通用換行轉掉。

用法:
    python3 tools/merge_tutorial.py                     # temp + text -> text
    python3 tools/merge_tutorial.py BASE.xml OLD.xml OUT.xml
"""

import html
import os
import re
import sys

PAIRS = [("EN", "KR"), ("ENGROUP", "KRGROUP")]
KOR_TO_ENG = {kor: eng for eng, kor in PAIRS}

CJK_RE = re.compile(r"[一-鿿぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
TI_RE = re.compile(r'<TI (?P<attrs>[^>]*)>(?P<body>.*?)</TI>', re.S)

DEFAULT_BASE = "temp/tutorial_data.xml"
DEFAULT_OLD = "text/tutorial_data.xml"
DEFAULT_OUT = "text/tutorial_data.xml"


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def tag_value(body, tag):
    m = re.search(r"<" + tag + r">(.*?)</" + tag + r">", body, re.S)
    return m.group(1) if m else None


def load_translations(path):
    """撈出舊檔所有含中日文的 <KR>/<KRGROUP>，key 為 (i, tag)。"""
    out = {}
    for m in TI_RE.finditer(read(path)):
        i = re.search(r'i="(\d+)"', m.group("attrs")).group(1)
        for kor in KOR_TO_ENG:
            v = tag_value(m.group("body"), kor)
            if v is not None and CJK_RE.search(html.unescape(v)):
                out[(i, kor)] = v
    return out


def merge(base, old, out_path):
    translations = load_translations(old)
    stats = {"kept": 0, "from_english": 0, "untouched": 0, "no_source": 0}

    def fix_ti(m):
        i = re.search(r'i="(\d+)"', m.group("attrs")).group(1)
        body = m.group("body")

        for eng, kor in PAIRS:
            cur = tag_value(body, kor)
            if cur is None:
                continue

            key = (i, kor)
            if key in translations:
                new_val = translations[key]
                stats["kept"] += 1
            elif HANGUL_RE.search(html.unescape(cur)):
                new_val = tag_value(body, eng)
                if new_val is None:
                    stats["no_source"] += 1
                    continue
                stats["from_english"] += 1
            else:
                stats["untouched"] += 1
                continue

            if new_val != cur:
                body = body.replace(
                    f"<{kor}>{cur}</{kor}>", f"<{kor}>{new_val}</{kor}>", 1)

        return f'<TI {m.group("attrs")}>{body}</TI>'

    result = TI_RE.sub(fix_ti, read(base))

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(result)
    os.replace(tmp, out_path)

    print(f"基底 {base} + 翻譯 {old} -> {out_path}")
    print(f"  舊檔可用的中文翻譯 : {len(translations)}")
    print(f"  保留中文翻譯       : {stats['kept']}")
    print(f"  韓文改填英文       : {stats['from_english']}")
    print(f"  原樣保留(非韓文)   : {stats['untouched']}")
    if stats["no_source"]:
        print(f"  無來源、維持韓文   : {stats['no_source']}")


ALL_TAGS = ["EN", "KR", "ES", "JP", "CN",
            "ENGROUP", "KRGROUP", "ESGROUP", "JPGROUP", "CNGROUP"]


def parse(path):
    out = {}
    for m in TI_RE.finditer(read(path)):
        i = re.search(r'i="(\d+)"', m.group("attrs")).group(1)
        out[i] = (m.group("attrs"),
                  {t: tag_value(m.group("body"), t) for t in ALL_TAGS})
    return out


def verify(out_path, base, old):
    O = parse(out_path)
    B = parse(base)
    D = parse(old)
    u = html.unescape
    ok = True

    print(f"檢查 {out_path}")
    print(f"  TI 筆數               : {len(O)}")
    if set(O) != set(B):
        print("  TI 集合與基底不符!")
        ok = False

    hangul = len(HANGUL_RE.findall(read(out_path)))
    print(f"  殘留韓文字元          : {hangul}")
    ok = ok and hangul == 0

    # KR/KRGROUP 以外的標籤與 TI 屬性必須與基底完全相同
    drift = 0
    examples = []
    for i in O:
        if i not in B:
            continue
        if O[i][0] != B[i][0]:
            drift += 1
        for t in ALL_TAGS:
            if t in KOR_TO_ENG:
                continue
            if O[i][1][t] != B[i][1][t]:
                drift += 1
                if len(examples) < 3:
                    examples.append((i, t))
    print(f"  其他標籤偏離基底      : {drift}", examples if examples else "")
    ok = ok and drift == 0

    # 舊檔的中文翻譯必須全數保留
    lost = []
    for i, (_, fields) in D.items():
        for kor in KOR_TO_ENG:
            v = fields[kor]
            if v is not None and CJK_RE.search(u(v)):
                if i not in O or O[i][1][kor] != v:
                    lost.append((i, kor))
    print(f"  遺失的中文翻譯        : {len(lost)}", lost[:5] if lost else "")
    ok = ok and not lost

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
