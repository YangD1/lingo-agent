# 0060 · 字体可选，默认 Inter + 思源黑体

- **状态**：已采纳（2026-10-21，任务 119；用户定：四个选项，默认 Inter + 思源黑体；按浏览器记住；入口在设置页）
- **日期**：2026-10-21
- **影响**：**修订 ADR 0059**：霞鹜文楷从全站唯一字体改成可选项之一，切片做法沿用并推广到每套字体。Geist Mono 不变。只改前端。

## 背景
ADR 0059 把全站换成霞鹜文楷。手写风格有人喜欢，也有人觉得长时间阅读、看数字和表格时不如黑体清楚。用户希望提供几个字体选项，默认用思源黑体加一款开源英文字体。

## 决定

### 1. 四个选项
| 选项 | 英文 | 中文 | 音标 |
|---|---|---|---|
| `sans`（默认） | Inter | Noto Sans SC（思源黑体） | Inter 自带 |
| `wenkai` | 霞鹜文楷 | 霞鹜文楷 | 霞鹜文楷自带 |
| `serif` | Source Serif 4 | Noto Serif SC（思源宋体） | Noto Serif 补（Source Serif 4 缺 IPA） |
| `system` | 系统字体 | 系统字体 | 系统字体 |

- 全部 SIL OFL 1.1，许可证在 `frontend/src/fonts/LICENSE-*.txt`。思源的保留字体名是 “Source”，CSS 里用 “Noto Sans SC” / “Noto Serif SC” 的名字，没有冲突。
- Inter、思源黑体、思源宋体、Source Serif 4 都是可变字体，保留字重轴，`font-semibold` / `font-bold` 是真粗体；其他轴（光学尺寸、宽度）固定在默认值，减小体积。霞鹜文楷仍按 0059：Regular + Medium，粗体显示成 Medium。
- 等宽字体仍是 Geist Mono，不参与选择。

### 2. 按浏览器记住，首次绘制前就生效
- 选择存在 `localStorage` 的 `lingo.font`，不进服务器（和其他显示偏好一样，换设备回到默认）。
- `layout.tsx` 的 `<head>` 里有一段内联脚本（`FONT_BOOT_SCRIPT`，`lib/font-choice.ts`），在 React 之前读出选择、设置 `<html data-font=…>`，并且只链接这一套的 `/fonts/<choice>/font.css`。页面不会先用默认字体再跳变；没选的字体一个文件都不下载。读不到 `localStorage`（隐私模式、被禁用）或值不认识时用默认。
- `globals.css` 里每套字体一个 `--font-stack-*`，`:root[data-font=…]` 切换 `--app-font`，`--font-sans` / `--font-heading` 指向它。
- 设置页“显示”一节列出四张卡片，每张用对应字体显示样例（中英文 + 音标）；点选立即生效。设置页会加载全部三套 `font.css` 以便预览，实际下载的只是样例用到的那几片。

### 3. 切片（沿用 0059，脚本改成通用）
- `frontend/scripts/build-fonts.py` 生成 `public/fonts/{sans,serif,wenkai}/` 和各自的 `font.css`。`src/app/wenkai.css` 删除。
- 西文字体切 `latin` / `symbols`；中文字体切 `ui` / `hot-N` / `gb-N`（同 0059）；`serif` 另有 Noto Serif 的 `ipa` 片。`latin` 收窄到拉丁扩展 A 为止，扩展 B 和越南文等进 `symbols`。

## 取舍
- **体积**：入库 sans 约 2.7 MB、serif 约 3.5 MB、wenkai 约 4.4 MB。默认字体下一个中文页面首次通常下载 `inter-latin`（约 130 KB）+ `notosanssc-ui`（约 280 KB）+ 少量 `hot` 片。
- **内联脚本**：多一段约 400 字节的脚本，换来没有字体闪变。Next 官方文档推荐这种做法（`preventing-flash-before-hydration`）。
- **不存服务器**：换浏览器要重选一次；好处是不需要接口和迁移，登录页也能生效。
