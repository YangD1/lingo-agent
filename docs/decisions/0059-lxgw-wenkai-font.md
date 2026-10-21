# 0059 · 全站字体换成霞鹜文楷（中英文同一套）

- **状态**：已采纳（2026-10-21，任务 118；用户定：普通版 Regular + Medium，semibold / bold 显示成 Medium，等宽保留 Geist Mono）。**已被 ADR 0060 修订**：霞鹜文楷改为可选字体之一，默认 Inter + 思源黑体；脚本改名 `build-fonts.py`，`wenkai.css` 改为 `public/fonts/wenkai/font.css`。
- **日期**：2026-10-21
- **影响**：**替换 ADR 0019 的“字体自托管”一条**（Figtree + 中文系统字体 → 霞鹜文楷）。Geist Mono 不变。只改前端。

## 背景
ADR 0019 用 Figtree（只有拉丁子集）显示英文，中文走系统字体，不同系统看到的中文不一样，中英文混排的字形也对不上。单词弹窗、生词本显示的音标（ə ʃ θ ˈ ː）不在 Figtree 子集里，会退回系统字体，和周围的字不一致。用户希望换成一套好看的开源字体。

## 决定

### 1. 字体：霞鹜文楷 LXGW WenKai（v1.530，普通版）
- 中文、英文、IPA 音标、常用标点同一套字体，SIL OFL 1.1（`frontend/src/fonts/LICENSE-LXGWWenKai.txt`）。许可证的补充条款允许“仅为网页加载”而切子集、转 woff2 的版本继续使用 “LXGW” 名称，所以 `font-family` 保留原名。
- 只有 Light / Regular / Medium，没有 Bold。用 Regular（`font-weight: 100 449`）和 Medium（`450 900`）两档：`font-semibold` / `font-bold` 显示成 Medium，不让浏览器模拟加粗（中文笔画会糊）。
- 不用屏幕阅读版（Screen）：笔画更粗、小字更清楚，但只有 Regular 一档。
- `--font-sans` / `--font-heading`：`"LXGW WenKai"` 在前，系统中文字体垫后。代码块仍用 Geist Mono。

### 2. 按 unicode-range 切片，浏览器只下载用到的
- `frontend/scripts/build-wenkai-fonts.py`（`uv run --with fonttools --with brotli`，不进项目依赖）从官方 release 的 TTF 生成 `public/fonts/wenkai/*.woff2` 和 `src/app/wenkai.css`（`globals.css` 引入）。生成物入库，构建时不访问外网。
- 切法（两档字重各一套）：
  - `latin`：英文含变音、IPA、通用标点、货币、箭头，约 75 KB——几乎每页都要；
  - `symbols`：其余非中日韩字符（希腊、西里尔、数学、制表符），约 70 KB，很少用到；
  - `ui`：中文界面文案（`messages/zh-CN.json`）用到的汉字 + 全角标点，约 210 KB——中文界面每页都要；
  - `hot-N`：其余汉字按 `docs/` 里中文出现频率排序，每片 150 字；
  - `gb-N`：GB2312 剩下的字，按码位每片 200 字。每片约 40 KB。
- GB2312 以外的生僻字不打包，退回系统中文字体。

### 3. 更新字体
下载新版 TTF 到一个空目录，重跑脚本（用法见脚本开头），连同许可证一起提交。改了中文界面文案不必每次重跑：新字只要在 GB2312 里，就落在 `hot` / `gb` 片里，只是多下载一片。

## 取舍
- **体积**：两档字重共约 4 MB 入库；一个中文页面首次通常下载 `latin` + `ui` + 若干片（几百 KB），之后浏览器缓存。比打包整套（每档约 10 MB）或 GB2312 整包（每档约 1.8 MB）都小。
- **`wenkai.css` 约 120 KB**（gzip 后小得多），每页都要加载，换来按需下载字体文件。
- **频率来源用 `docs/`**：没有引入外部字频表；`docs/` 是大量中文说明文字，足够把常用字排到前面。文档变化后重跑结果会略有不同，不影响正确性。
- **层级感变弱**：没有真 Bold，semibold / bold 和 medium 看起来一样。
