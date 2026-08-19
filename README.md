# ootp23-cht
OOTP 23 繁體中文化

## 原因
OOTP 有韓國版之後讓中文化有了可能性，再加上網路上搜尋到日本網友製作日文版的流程 (https://reurl.cc/l9eyNv) ，所以評估決定可行

## Demo畫面
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo1.png)
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo2.png)
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo3.png)
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo4.png)
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo5.png)
![遊戲頁面](https://bojin-pdfserver.s3.ap-northeast-1.amazonaws.com/demo6.png)

## 使用方式
- Step 1: 下載本專案的所有檔案
- Step 2: 找到你的 OOTP 23 的應用程式資料夾，將本專案的所有檔案依照對應的位置放入並覆蓋原先的檔案（建議先將原檔案備份，如中文化檔案導致遊戲損毀可用備份檔還原即可）
- Step 3: 執行 OOTP 23 在設定的地方將語言改成韓文，再次重新執行 OOTP 23 你就可以看到中文版了

## 現況
- 其實遊戲裡面已經有日文、簡體中文的翻譯片段，本中文化就是借用簡體中文的翻譯再轉成繁體中文
- 裡面還有大量的翻譯錯誤需要修改，也還有一部分都是韓文的，也需要再想辦法翻譯

### 主要需要翻譯的檔案有兩個：
1. gui_translations.xml (這個檔案主要是遊戲介面的文字部分，大部分都有翻譯了，但有非常多的翻譯錯誤需要修改，請記得改KR韓文標籤裡面的文字，改成正確的中文翻譯)

目前 `HARD_CODED_STRINGS` 與 `LEAGUE_NAMES` 已經沒有韓文和簡體字，剩下的是用詞問題（「設置/數據/信息/用戶」等對岸用語）與 142 條刻意留英文的字串。`TEAM_NAMES`（410 筆）和 `TEAM_NICKNAMES`（483 筆）整段還是韓文，是目前最大的缺口。翻好之後請跑 `python3 tools/merge_gui.py --verify` 確認。

範例：其中我們需要改的部分就是KR標籤 (```<KR>XXXX</KR>```) 裡面的字，如果有遇到%d這類的特殊符號請不要去改動它，只要改文字的部分就好。
```
<HCS i="18722">
   <EN>%d other players</EN>
   <DC></DC>
   <KR>%d 其他球員</KR>
   <ES>%d otros jugadores</ES>
   <JP>％d他のプレイヤー</JP>
   <CN>%d 其他球員</CN>
  </HCS>
 ```

2. korean.xml (這個檔案主要是比賽中的播報對話，還有遊戲介面裡面比較長的文字部分，都是英文的需要英翻中，請記得改KR韓文標籤裡面的文字，改成正確的中文翻譯)

### 介面文字 gui_translations.xml
`text/gui_translations.xml` 的 `<KR>` 由 `tools/merge_gui.py` 產生，規則依序是：

1. 程式裡的 `OVERRIDES` 有這個 `i` → 用人工翻譯（`<CN>` 是機翻、救不回來時走這條）
2. 舊檔的 `<KR>` 不是韓文、且不等於 `<CN>` → 保留舊檔的值（既有翻譯，或刻意留著的英文縮寫如 `%a OBP`、`AL`、`TFBL`）
3. `<CN>` 有中文 → 用 `<CN>` 轉繁體填入
4. 是韓文但 `<CN>` 沒中文可用 → 退回填 `<EN>`（如 `TOPPS`、`iPhone 13`）

規則 3、4 只套用在 `HARD_CODED_STRINGS` 與 `LEAGUE_NAMES`。`TEAM_NAMES` / `TEAM_NICKNAMES` 的 `<CN>` 是不能用的機翻（`Reading Fightin Phils` → 「閱讀格鬥菲爾斯」），那兩段還是韓文，要人工翻。

需要 opencc：
```
pip install opencc-python-reimplemented
python3 tools/merge_gui.py               # 基底 + text -> text
python3 tools/merge_gui.py --verify      # 只檢查不寫檔
```
遊戲改版時把新的原始檔放到 `temp/gui_translations.xml` 再執行同一行指令；沒有那個檔的話會拿 `text/gui_translations.xml` 自己當基底，等於就地把還沒中文化的部分補起來。其他標籤（`EN`/`DC`/`ES`/`JP`/`CN`）一律沿用基底，不做任何改動。

轉繁體用的是 opencc 的 `s2tw`（只換字不換詞）。之後若要把「設置/數據/信息」一併換成「設定/資料/資訊」，把程式裡的 `OPENCC_CONFIG` 改成 `s2twp` 重跑即可。

### 人名字庫 names.xml
`database/names.xml` 不做中文翻譯，而是把 `<KR>` 直接換成 `<EN>` 的英文原名，因為遊戲內建的 `<CN>` 人名是機翻結果不堪使用（例：`A.C.` → `交流電`、`Aad` → `廣告`）。

遊戲改版拿到新的原始檔時，把它放到 `temp/names.xml`，再執行以下指令即可重新產生：
```
python3 tools/localize_names.py          # temp/names.xml -> database/names.xml
python3 tools/localize_names.py --verify # 只檢查不寫檔
```

### 學校資料 schools.xml
`database/schools.xml` 的四個 `*_KOREAN` 欄位有兩種來源：台灣、日本的學校是人工中文翻譯，其餘則退回英文原名。

遊戲改版時把新的原始檔放到 `temp/schools.xml`，執行以下指令會以新版原始檔為基底、把既有的中文翻譯合併回去：
```
python3 tools/merge_schools.py           # temp + database -> database/schools.xml
```
英文欄位（`CITY`/`NAME`/`NICK`/`ASSO`/`CONF` 等）一律沿用官方新版，不做任何改動。

### 世界地理資料 world_default.xml
`database/world_default.xml` 的 `name_korean` / `abbr_korean` / `dem_korean` / `short_korean` 四個屬性，處理原則與 schools.xml 相同：有人工中文翻譯的（國家、洲、族裔、台灣與日本的城市）保留中文，其餘退回英文原名。

遊戲改版時把新的原始檔放到 `temp/world_default.xml`，執行：
```
python3 tools/merge_world.py             # temp + database -> database/world_default.xml
```
英文屬性（`name`/`abbr`/`dem`/`short`）與經緯度、人口等資料一律沿用官方新版。本來就是拉丁字母、但刻意與英文不同的官方縮寫（例：`abbr="GUN" abbr_korean="GUM"`）會原樣保留，不會被覆蓋。

### 教學資料 tutorial_data.xml
`text/tutorial_data.xml` 的 `<KR>` 與 `<KRGROUP>` 已全部是中文，來源是 `<CN>`／`<CNGROUP>`（後者原為簡體，已轉繁體）加上少數人工改寫。

遊戲改版時把新的原始檔放到 `temp/tutorial_data.xml`，執行：
```
python3 tools/merge_tutorial.py          # temp + text -> text/tutorial_data.xml
```
其餘標籤（`EN`/`ES`/`JP`/`CN` 及各自的 GROUP）一律沿用官方新版。注意這個檔案有 6 筆標籤的值跨行、且值裡藏有 CRLF，處理時不能逐行取代。

## 希望
大家如果對棒球有興趣，或是熟悉OOTP的遊戲內容，也煩請的大家一起來貢獻，想辦法弄出一個大家期盼已久的中文版 OOTP
