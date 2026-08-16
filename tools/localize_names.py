#!/usr/bin/env python3
"""將 names.xml 的 <KR> 欄位改寫成 <EN> 的英文人名。

遊戲內建的 <CN> 人名是機翻結果，不堪使用（例：A.C. -> 交流電、Aad -> 廣告），
所以人名字庫的做法是讓韓文欄位直接顯示英文原名。

用法:
    python3 tools/localize_names.py                     # temp/names.xml -> database/names.xml
    python3 tools/localize_names.py IN.xml OUT.xml
    python3 tools/localize_names.py --verify OUT.xml    # 只檢查，不寫檔

刻意採用逐行字串取代而非 XML 重新序列化：原檔的排版與實體跳脫必須原封不動，
重新序列化除了製造無謂的差異，也有掉資料的風險。
"""

import os
import re
import sys

EN_RE = re.compile(r"<EN>(.*?)</EN>")
KR_RE = re.compile(r"<KR>.*?</KR>")
HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

DEFAULT_SRC = "temp/names.xml"
DEFAULT_DST = "database/names.xml"


def convert(src, dst):
    lines = 0
    rewritten = 0
    already = 0
    anomalies = []

    tmp = dst + ".tmp"
    with open(src, encoding="utf-8", newline="") as fin, \
         open(tmp, "w", encoding="utf-8", newline="") as fout:
        for lineno, line in enumerate(fin, 1):
            lines += 1
            if "<KR>" not in line:
                fout.write(line)
                continue

            en = EN_RE.search(line)
            if en is None:
                # 有 KR 卻沒有 EN，沒有可靠的來源可用，原樣保留
                anomalies.append(lineno)
                fout.write(line)
                continue

            new_kr = "<KR>" + en.group(1) + "</KR>"
            new_line, n = KR_RE.subn(lambda _m: new_kr, line, count=1)
            if new_line == line:
                already += 1
            else:
                rewritten += 1
            fout.write(new_line)

    os.replace(tmp, dst)

    print(f"讀取 {src} -> 寫入 {dst}")
    print(f"  總行數      : {lines}")
    print(f"  改寫記錄    : {rewritten}")
    print(f"  原本已相同  : {already}")
    print(f"  異常(無 EN) : {len(anomalies)}"
          + (f" 行號 {anomalies[:10]}" if anomalies else ""))
    return len(anomalies)


def verify(path, src=None):
    """檢查輸出檔：KR 全等於 EN、沒有殘留韓文，且其他欄位未被更動。"""
    with open(path, encoding="utf-8", newline="") as f:
        out = f.read()

    records = re.findall(r'<N nid="\d+"[^>]*>.*?</N>', out)
    mismatched = 0
    for rec in records:
        en = EN_RE.search(rec)
        kr = re.search(r"<KR>(.*?)</KR>", rec)
        if en is None or kr is None or en.group(1) != kr.group(1):
            mismatched += 1

    hangul = len(HANGUL_RE.findall(out))

    print(f"檢查 {path}")
    print(f"  記錄數        : {len(records)}")
    print(f"  KR != EN      : {mismatched}")
    print(f"  殘留韓文字元  : {hangul}")

    ok = mismatched == 0 and hangul == 0

    if src:
        with open(src, encoding="utf-8", newline="") as f:
            original = f.read()
        src_records = re.findall(r'<N nid="\d+"[^>]*>.*?</N>', original)
        if len(src_records) != len(records):
            print(f"  記錄數與原檔不符: 原檔 {len(src_records)}")
            ok = False
        else:
            polluted = 0
            for a, b in zip(src_records, records):
                if KR_RE.sub("", a) != KR_RE.sub("", b):
                    polluted += 1
            print(f"  KR 以外欄位遭更動: {polluted}")
            ok = ok and polluted == 0

    print("  結果          : " + ("PASS" if ok else "FAIL"))
    return ok


def main(argv):
    if "--verify" in argv:
        argv = [a for a in argv if a != "--verify"]
        target = argv[0] if argv else DEFAULT_DST
        source = argv[1] if len(argv) > 1 else None
        return 0 if verify(target, source) else 1

    src = argv[0] if argv else DEFAULT_SRC
    dst = argv[1] if len(argv) > 1 else DEFAULT_DST
    convert(src, dst)
    return 0 if verify(dst, src) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
