# 组件规格

所有颜色都写 token 名（见 `tokens.css`），浅色 / 深色自动切换。基准圆角 `--radius: 0.75rem`：sm 8 · md 10 · lg 12 · xl 16。图标统一 Lucide，线宽 2（默认），按钮内 16px、导航 18px、标签栏 22px。

完整的样式实现可以对照 `mockup-reference.css`（设计稿用的 CSS，类名和这里一一对应）。

## 状态通则

| 状态 | 规则 |
| --- | --- |
| 悬停 | 实心按钮：底色与 `foreground` 混合 12%；描边/幽灵按钮：底色变 `accent` |
| 按下 | 实心按钮混合 22%；描边/幽灵按钮在 `accent` 基础上再加深 15% |
| 禁用 | 不透明度 45%，不响应指针 |
| 聚焦 | `outline: 2px solid var(--ring); outline-offset: 2px`，所有可聚焦元素统一 |
| 触屏 | ≤ 760px 时按钮、输入框最小高度 40px，底部标签栏 64px |

## 1. 按钮

| 变体 | 底色 | 文字 | 边框 |
| --- | --- | --- | --- |
| default | `primary` | `primary-foreground` | — |
| outline | `card` | `foreground` | 1px `input` |
| secondary | `secondary` | `secondary-foreground` | — |
| ghost | 透明 | `foreground` | — |
| destructive | `destructive` 10% | `destructive` | — |
| link | 透明 | `primary`，悬停下划线（偏移 3px） | — |
| 危险确认（仅对话框里） | `destructive` | `destructive-foreground` | — |

| 尺寸 | 高 | 左右内边距 | 字号 / 字重 | 圆角 |
| --- | --- | --- | --- | --- |
| xs | 24 | 8 | 12 / 550 | sm 8 |
| sm | 32 | 10 | 13 / 550 | md 10 |
| default | 36（手机 40） | 14 | 14 / 550 | md 10 |
| lg | 44 | 20 | 15 / 550 | lg 12 |
| icon | 正方形，同高 | 0 | — | 同尺寸 |

图标与文字间距 6（xs 为 4）。

## 2. 卡片

- 底 `card`，1px `border`，圆角 xl 16，**不加阴影**。
- 头部：内边距 18 / 22 / 0；标题 16 / 600；描述 13 `muted-foreground`；右上角操作区右对齐，按钮用 ghost sm。
- 内容：内边距 18 / 22 / 20（手机 14 / 16 / 16）。
- 底部：上边线 1px `border`，内边距 12 / 22。
- 紧凑卡片：圆角 lg 12，内边距 14。

## 3. 表单

- 输入框：高 36（手机 40），内边距 0 12，圆角 md，1px `input`，底 `card`，字号 14。悬停边框加深；错误边框 `destructive`，下方一行错误文字（13，带 circle-alert 图标）。
- 多行文本框：最小高 84，内边距 9 12，行高 1.6。
- 原生下拉框：右侧 chevron-down 16px（`muted-foreground`），右内边距 32。
- 带候选的输入框：候选列表是弹出层样式（见第 5 条），每项最小高 32、圆角 sm、**等宽字体**；已输入部分用 `primary` + 600 字重高亮；当前项底色 `accent`。
- 复选框 18×18，圆角 5，1.5px `input`；选中填 `primary`，勾 13px。单选 18 圆形，选中为 `primary` 描边 + 8px 实心点。
- 滑块：轨道 4px `muted`，填充 `primary`，滑块 18 圆形白底 2px `primary` 描边；数值在右上角等宽显示（“0.9×”）。
- 数字输入：一体式，高 36，左右各 34 宽的减 / 加按钮，中间等宽数字最小宽 56。

## 4. 分段切换

外框底 `muted`、内边距 3、圆角 md；选项高 28（sm 24），选中项白底 `card` + `--shadow-lift` + 600 字重，未选中 `muted-foreground`。

## 5. 弹出层

底 `popover`，1px `border`，圆角 lg 12，阴影 `--shadow-pop`，内边距 14 / 16。

- **单词气泡**：宽 320。单词 20 / 700，音标等宽 13 `muted-foreground`，朗读图标按钮 xs；“原形 go”12；释义最多 3 行（14 / 1.7）；小标题“原句”11.5 / 650；“AI 例句”是 outline xs 按钮 + AI 标记，展开后是 `muted` 底的块，英文句 + 灰色中文；底部整宽 secondary sm “加入生词本”，加入后换成成功文字。
- **正文中的单词**：默认无下划线；悬停 0.3 秒后底色 `brand-soft`（四周外扩 2px），气泡打开时保持高亮并用 `brand-soft-foreground` 文字。手机上气泡改为底部弹出。
- **朗读设置**：宽 320，内容同设置页“朗读”卡。

## 6. AI 标记

- 符号（任务 27.1 起，替代原来带 “AI” 字样的胶囊）：只有四角星图标（Lucide sparkles）12px，颜色 `ai`，无底无字；点击区 16×16 圆形，悬停底色 `ai` 14% 混 `card`。读屏靠 `aria-label`（“用到 AI…”）。
- 位置：紧跟在按钮或标题后面（间距 2–6）；或贴在按钮右上角（top −6，right −6），垫一块 `background` 色圆底与按钮边框隔开。
- 说明弹出层宽 340：标题行（✦ + 一句功能描述）；每次模型调用一块：任务名（600）、时机（等宽、右对齐）、“约 X 输入 + Y 输出 token”、模型名（等宽）、估计来源（11px）；块之间 1px 分隔；底部一句“只显示 token 数，价格取决于你的模型服务商。”
- `ai` 色只给 AI 标记用，不用于其他标签（“新词”等用中性标签）。

## 7. 页内提示条

内边距 10 / 12 / 10 / 14，圆角 lg，左侧 18px 图标，主按钮 default sm，关闭按钮 ghost sm 图标。

| 类型 | 底 | 边框 | 图标色 |
| --- | --- | --- | --- |
| 品牌（入学测提示） | `brand-soft` | `brand` 18% | `brand-soft-foreground` |
| 中性（练习条、重新测试） | `muted` | `border` | `muted-foreground` |
| 警告（未配置模型） | `warning` 10% | `warning` 25% | `warning` |

## 8. 行内状态文字

13px，左侧 15px 图标，间距 6：成功 `success` + circle-check，警告 `warning` + triangle-alert，错误 `destructive` + circle-alert。

## 9. 快捷回复胶囊

最小高 34，内边距 6 / 14，圆角 999，1px `input`，底 `card`，字号 14；右对齐、间距 8、可换行。悬停底色 `brand-soft`、边框 `brand` 35%。

## 10. 标签 / 徽标

- 通用标签：高 20，内边距 0 7，圆角 6，11.5 / 600。变体：默认（`secondary`）、outline、brand（“当前”）、success、warning。
- **CEFR**：等宽字体 11.5 / 650，后面跟 6 格刻度（2×8px 竖条，已达到的格为实色），颜色是同一色相由浅到深：A1 中性灰 → A2/B1 浅珊瑚 → B2 中珊瑚 → C1 主色白字 → C2 深珊瑚白字。刻度保证不靠颜色也能读出顺序。

## 11. 进度条

高 6（细条 4，堆叠图表 8–14），圆角 999，轨道 `muted`。单色：`primary`；掌握度三色：薄弱 `chart-3`、学习中 `chart-2`、已掌握 `chart-1`；堆叠段之间 1.5px `card` 色缝；旁边总有“62% · 学习中”这样的文字。

## 12. 表格

外框 1px `border`、圆角 lg；表头 12 / 550 `muted-foreground`、底 `muted`；单元格内边距 9 / 12，行间 1px `border`；数字列右对齐 + 等宽 + tabular-nums；合计行 650 字重、底 `muted` 55%；窄屏外框横向滚动，单元格不折行。

## 13. 列表行

最小高 48，上下内边距 12，行间 1px `border`；主信息 14 / 550，次要信息 12.5 `muted-foreground`；右侧操作用 ghost sm。

## 14. 可折叠行

最小高 48；左侧 chevron-right 16px（展开时旋转 90°），`aria-expanded`；展开内容左缩进 26；证据项之间 1px 虚线；删除线用 `destructive` 70% 的线色 + `muted-foreground` 文字，改正后的写法 `success` + 550。

## 15. 确认方式

- 可撤销的操作：保留“按钮原地变成 确定 / 取消”（destructive sm + ghost sm）。
- 不可恢复的操作（删除所有学习记录、忘掉全部事实、删除全部摘要）：用对话框替代浏览器原生 confirm。对话框宽 420，圆角 xl，内边距 22，标题 16 / 600，说明 13 `muted-foreground`，右下角“取消”（ghost）+“删除”（实心危险色）。遮罩 `foreground` 32%。

## 16. 加载、空状态、错误

- 骨架屏：`muted` 色块，圆角 6，按真实布局摆放（标签 12 高、标题 28 高、正文 10 高）。
- 空状态：居中，44px 圆角方块里放一个 20px Lucide 图标 → 一句加粗“现在是什么情况” → 一句“做什么会变好” → 一个 outline sm 按钮。不做插图。
- 错误：同空状态结构，图标块用 `destructive` 10% 底 + `destructive` 图标，按钮是“重试”。

## 应用外壳

- 桌面左侧栏宽 248，底 `sidebar`，右边线 `sidebar-border`；导航项高 38、圆角 md、图标 18；当前项底 `sidebar-accent`、文字 `sidebar-accent-foreground` + 600；分组标题 11.5 / 600。用户区固定在底部。对话页侧栏收成 64px 图标栏（悬停有 tooltip）。
- 页面内容最大宽 1160，内边距 32 / 40；手机 20 / 16。
- 手机（≤ 760px）：顶栏 56（logo 24 + 页面标题），底部标签栏 64（看板 · 对话 · 背单词 · 进度 · 更多），“更多”是底部弹出面板。对话页隐藏标签栏，会话列表变成左侧抽屉（宽 300）。

## 对话页

- 会话列表宽 256；行高 36、圆角 md；当前行底 `accent` + 600；悬停出现 trash-2（ghost xs）。特殊会话图标 14px：语法练习 target、学习规划 compass、今天的学习 sun。
- 消息列最大宽 768 居中，消息间距 22。
- 用户消息：底 `primary`、文字 `primary-foreground`，圆角 18 18 6 18，内边距 10 / 15，最大宽 78%（手机 86%）。
- 私教消息：30px 头像（`brand-soft` 底 + logo 20px），气泡底 `card` + 1px `border`，圆角 6 18 18 18，内边距 14 / 18，正文 16 / 1.75（Markdown：引用块、代码、表格用 `muted` 底）。
- 工具行：12.5px，按钮高 28、圆角 sm，图标 14，分组用 1px 竖线。
- 私教卡片：圆角 lg，内边距 12 / 14，左侧 32px 图标块（品牌浅底；已执行用成功色；已拒绝 / 已撤销用中性色并透明底）。
- “私教做了什么”：折叠时一行 12.5px `muted-foreground` + chevron；展开后底色 `muted` 60% 混 `background`、圆角 lg、内边距 12 / 14，分段小标题 11.5 / 650，底部链接行。
- 输入区：圆角 18，1px `input`，`--shadow-lift`；左侧竖排两个图标按钮（各带 AI 标记），中间输入（最小高 64，15px），右侧“发送”（default + AI 标记，流式时变成 outline 图标按钮“停止”）。
- 录音中：红点 10px（`destructive` + 4px 20% 光晕）、等宽计时、音量电平条（3px 宽竖条）、“放弃”；录音按钮变成实心 `destructive` 停止按钮。
- 附件托盘：每项宽 236（手机整宽），36px 缩略图，文件名 12.5 / 550，状态 11.5（成功 `success`、失败 `destructive`）。
- 拖入：整个对话区上方覆盖 2px 虚线（`primary` 60%）、圆角 20、底 `background` 82%，中间 file-up 图标 + “松开即可添加附件”。
