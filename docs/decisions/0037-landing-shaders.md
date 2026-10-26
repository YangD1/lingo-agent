# 0037 · 首页（未登录）用 WebGPU shader 做动态背景

- **状态**：~~已采纳~~ 已被 ADR 0065 取代（2026-10-26，首页改成放大镜单词墙，shader 背景和 `shaders` 依赖去掉）。原状态：已采纳（2026-10-14，任务 74；用户在两轮草稿 A/B/C、A2/C2 中选了 A2“流光”，Q74a–c 全部按推荐确认）
- **日期**：2026-10-14
- **影响**：前端新增依赖 `shaders`（shaders.com，MIT，4.0.4，依赖 typegpu）；`components/home/landing*.tsx` 重写；`globals.css` 新增 `.landing-silk` / `.landing-ink` 两个 CSS 底色。只影响未登录首页，其他页面不加载这个库。

## 背景
- 首页是项目给人的第一印象，原来是平铺的白底加卡片，和 ADR 0036 改版后的应用内页比，显得单薄。
- 用户希望首页更现代，指定用 `shaders` 库做动态背景，配色沿用品牌色（珊瑚、琥珀、靛蓝、墨色，ADR 0019）。

## 决定
- **A2 流光**：首屏是一块圆角区域，背景为 MeshGradient（品牌色六个色标、oklab 插值），叠加 FlutedGlass（竖向棱纹玻璃）、CursorRipples（鼠标涟漪）和 FilmGrain（颗粒）。下方依次是重叠在首屏上的对话演示卡片、纠错跑马灯、6 格功能卡片、透明度说明区，以及墨色 FlowingGradient 背景的结尾 CTA。
- **跟随系统主题（Q74a）**：浅色用奶油到珊瑚的丝光；深色改用墨色底，配靛蓝和珊瑚。结尾 CTA 始终是深色。
- **两层拆分、懒加载（Q74b）**：
  - `landing-backdrop.tsx`：轻量层，服务端 HTML 就带着 CSS 底色（渐变加条纹，模拟同一种观感）。
  - `landing-shaders.tsx`：WebGPU 层，通过 `next/dynamic`（`ssr: false`）加载，GPU 就绪（`onReady`）后用 1 秒淡入盖住底色。`onUnavailable` 时保留底色。
  - 浏览器没有 `navigator.gpu` 时根本不加载这个 chunk。
- **动效强度不变（Q74c）**：MeshGradient speed 1.6，加鼠标涟漪。系统开了“减少动态效果”时，所有 speed 和涟漪强度设为 0，画面静止；跑马灯和卡片悬浮位移也关掉。
- **关闭遥测**：`<Shader disableTelemetry>`。库默认会对非 localhost 的站点抽样 5%，上报到 `shaders.com/api/telemetry`（见 `core/telemetry/index.js`）。关掉后，首页不发出任何第三方请求，符合自部署的定位。
- **无障碍**：背景层都设了 `aria-hidden` 和 `pointer-events-none`。演示卡片、跑马灯和插图是装饰，也设了 `aria-hidden`，同样的信息在卡片文字里都有。
- **防止 hydration 不一致**：`resolvedTheme` 在服务端没有值，所以 shader 只在客户端挂载后渲染。

## 取舍
- **体积**：这个库没有按组件拆分的 React 入口，每个组件都会引入 `core/index.js`，而它会引入全部 200 多个着色器。打包后单个 chunk 2.5MB，gzip 后约 730KB，无法摇树。
  - 懒加载后不计入首屏：`/` 首屏的客户端 chunk gzip 后约 93KB。
  - 只在首页、只在支持 WebGPU 的浏览器下载，其他页面的清单里都没有它（`next build` 实测）。
  - 以后如果嫌大，可以换成手写 WGSL 或者 CSS 版本，接口仍然是 `ShaderProps`。
- **WebGPU 覆盖面**：Chrome/Edge 桌面和 Android、Safari 26+ 支持。其他浏览器只显示 CSS 底色，静态，但配色和版式一样。
- **耗电**：动画持续占用 GPU。只有首页有，登录后的应用内页面不受影响。
- **测试**：无头 Chromium 的 WebGPU 不稳定，所以 E2E 和截图看到的是 CSS 底色。shader 效果只能在真实浏览器里人工确认。
