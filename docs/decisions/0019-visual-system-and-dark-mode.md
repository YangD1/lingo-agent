# 0019 · 视觉系统与深色主题

- **状态**：已采纳
- **日期**：2026-10-01

## 背景
P1 的界面用的是 shadcn 默认的黑白灰配色，只有浅色，个别地方写死了 violet / emerald / amber，没有品牌资源，中文字体也没设置。任务 26 用 Claude Design 从猫咪 logo 出发做了一套视觉系统，交付包在 `docs/design/lingo-agent-design/`（配色变量、字体清单、组件规格、设计稿）。需要定下怎么接进前端，之后改页面都按这里来。

## 决定
- **配色只认 token**：设计包里的 `tokens.css` 原样并入 `frontend/src/app/globals.css`，包括 `:root` 和 `.dark` 两段，值用 OKLCH。组件里只用 token 生成的工具类（`bg-primary`、`text-ai`、`bg-heat-3`……），不写 Tailwind 调色板颜色。新增的语义 token 有 `brand` / `brand-soft`（品牌点缀、提示条、单词高亮）、`success`、`warning`、`ai`（只给 AI 标记用）、`heat-0..4`（学习日历）、`spark`（只给 logo 用）。
- **主色压深**：界面主色用陶土珊瑚 `#C8441F`，白字对比度 4.9:1。logo 原色 `#F25C3B` 只用于 logo 和小面积点缀，不做文字底色。深色主题反过来，用亮珊瑚做主色，上面放深色字。
- **深色主题**：`next-themes`，`attribute="class"`，“跟随系统 / 浅色 / 深色”三档，选择存在当前浏览器的 localStorage，不进用户资料。切换控件放在侧栏用户区和手机“更多”面板。
- **字体自托管**：Figtree（英文、数字）和 Geist Mono（等宽）的拉丁子集可变字体放在 `frontend/src/fonts/`，用 `next/font/local` 加载，附 OFL 许可证。构建时不访问 Google Fonts，在代理或离线环境里也能构建。中文走系统字体栈，不打包中文字体（完整的 Noto Sans SC 每个字重约 8MB）。
- **logo 内联**：猫咪图标用内联 SVG 组件（`components/brand/logo.tsx`），颜色取 `var(--brand)`，跟着主题切换。favicon、apple-touch-icon 按 Next 的文件约定放在 `src/app/`。
- **组件规格**：尺寸、圆角、状态以 `component-spec.md` 为准。卡片用细描边、不加阴影；阴影只给弹出层（`--shadow-pop`）和浮起的元素（`--shadow-lift`），写成 `shadow-(--shadow-pop)`。焦点统一是 2px `ring` 色描边加 2px 间隙。
- **断点**：设计稿的手机断点是 760px，实现直接用 Tailwind 的 `md`（768px），不另加自定义断点。手机上按钮和输入框高 40px。

## 取舍
- 拉丁子集里没有越南语等扩展字符，遇到时回退到系统字体，混排时字形会不一致。目前的学习内容都是英语，可以接受。
- 中文用系统字体，在不同系统上看起来会有差别（苹方、雅黑、思源黑体），换来的是零下载体积。
- 主题存在浏览器里，换一台设备需要重新选，和 ADR 0018 里朗读设置的做法一致。
