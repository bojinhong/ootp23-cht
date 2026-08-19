#!/usr/bin/env python3
"""把一份 id<TAB>中文 的 TSV 套進 text/korean.xml。

`merge_korean.py --todo` 吐出來的格式是 分類<TAB>id<TAB>英文，翻好之後照
id<TAB>中文 餵回來就好（多欄的話取第一欄當 id、最後一欄當譯文）。

上線的那筆和被註解掉的同 id 都會一起換，這樣之後重跑 merge_korean.py 不會
把翻譯洗掉。寫檔前會逐筆檢查（PROGRESS.md 列的那四項），有問題就中止不寫。

用法:
    python3 tools/apply_zh.py batch.tsv            # 套用
    python3 tools/apply_zh.py batch.tsv --check    # 只檢查不寫檔
"""

import html
import re
import sys

TARGET = "text/korean.xml"

PLACEHOLDER_RE = re.compile(r"\[%[^\]]*\]")
BRACE_RE = re.compile(r"\{[^}]*\}")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def strip_markup(s):
    """去掉佔位符、{a|b} 選項與 (nl)，剩下的才是真正要看的譯文。"""
    s = PLACEHOLDER_RE.sub(" ", s)
    s = BRACE_RE.sub(" ", s)
    return s.replace("(nl)", " ")


def check(oid, en, zh):
    """回傳問題字串清單，空的代表這筆沒問題。"""
    bad = []
    en_ph, zh_ph = PLACEHOLDER_RE.findall(en), PLACEHOLDER_RE.findall(zh)
    if sorted(en_ph) != sorted(zh_ph):
        bad.append(f"佔位符不符 {en_ph} -> {zh_ph}")
    if en.count("(nl)") != zh.count("(nl)"):
        bad.append(f"(nl) 數量不符 {en.count('(nl)')} -> {zh.count('(nl)')}")
    if '"' in zh:
        bad.append("譯文含有半形雙引號，會破壞 XML 屬性")
    # {He|She|They} 是依性別選分支的。中文常常整個代名詞都不用寫，少幾個沒關係，
    # 但寫出來的每一個分支數都要對得上英文，不然遊戲會選到不存在的分支。
    en_arity = {b.count("|") for b in BRACE_RE.findall(en)}
    zh_arity = {b.count("|") for b in BRACE_RE.findall(zh)}
    if zh_arity - en_arity:
        bad.append(f"{{a|b}} 分支數不符 {sorted(en_arity)} -> {sorted(zh_arity)}")
    left = ASCII_WORD_RE.findall(strip_markup(zh))
    if left:
        bad.append(f"殘留英文單字 {left}")
    return [f"{oid}: {m}" for m in bad]


def load(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                sys.exit(f"這行不是 id<TAB>中文: {line[:60]}")
            rows[cols[0]] = cols[-1]
    return rows


def main(argv):
    check_only = "--check" in argv
    argv = [a for a in argv if a != "--check"]
    if not argv:
        sys.exit(__doc__)
    rows = load(argv[0])

    with open(TARGET, encoding="utf-8", newline="") as f:
        text = f.read()

    problems, hits = [], {}

    def sub(m):
        block = m.group(0)
        oid = re.match(r'<OBJ id="(\d+)"', block).group(1)
        zh = rows.get(oid)
        if zh is None:
            return block
        # 註解裡的 OBJ 已經把連續的 - 拆開過，比對英文時要看實際存在的那份
        for pat, wrap in ((r'text="([^"]*)"', 'text="%s"'),
                          (r"<TXT>(.*?)</TXT>", "<TXT>%s</TXT>")):
            hit = re.search(pat, block, re.S)
            if hit:
                problems.extend(check(oid, html.unescape(hit.group(1)), zh))
                hits[oid] = hits.get(oid, 0) + 1
                return block.replace(hit.group(0), wrap % zh, 1)
        return block

    out = re.sub(r"<OBJ [^>]*?(?:/>|>.*?</OBJ>)", sub, text, flags=re.S)

    missing = sorted(set(rows) - set(hits))
    if missing:
        problems.append(f"這些 id 在檔案裡找不到: {missing[:10]}")
    if problems:
        print("\n".join(problems[:40]))
        sys.exit(f"共 {len(problems)} 個問題，沒有寫檔")

    print(f"{len(rows)} 筆譯文檢查通過"
          + ("（--check，沒有寫檔）" if check_only else ""))
    if check_only:
        return 0
    with open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print(f"已寫入 {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
