# 字体清单

| 用途 | 字体 | 字重 | 来源 | 许可证 | 体积（woff2，拉丁子集） |
| --- | --- | --- | --- | --- | --- |
| 英文正文与标题 | **Figtree** | 400 / 500 / 600 / 700（可变 300–900） | Google Fonts · github.com/erikdkennedy/figtree · npm `@fontsource/figtree` | SIL OFL 1.1 | 每个字重约 11 KB |
| 等宽（模型名、用量表、计时、音标、CEFR 标签） | **Geist Mono** | 400 / 500 / 600 | github.com/vercel/geist-font · npm `geist` 或 `@fontsource/geist-mono` | SIL OFL 1.1 | 每个字重约 10 KB |
| 中文 | **系统字体栈**（默认，不打包） | 400 / 500 / 600 / 700 | 系统自带：PingFang SC → Hiragino Sans GB → Microsoft YaHei → Noto Sans CJK SC / Source Han Sans SC | — | 0 |
| 中文（可选） | Noto Sans SC 常用字子集 | 400 / 600 | github.com/notofonts/noto-cjk · npm `@fontsource/noto-sans-sc` | SIL OFL 1.1 | 完整版每个字重约 8 MB；3500 字子集约 1.2 MB |

## 接入方式（next/font/local，不访问外网）

```ts
// app/fonts.ts
import localFont from "next/font/local";
export const figtree = localFont({
  src: "../fonts/Figtree[wght].woff2", weight: "300 900", variable: "--font-figtree", display: "swap",
});
export const geistMono = localFont({
  src: "../fonts/GeistMono[wght].woff2", weight: "100 900", variable: "--font-geist-mono", display: "swap",
});
```

`tokens.css` 里的 `--font-sans` 已经把 Figtree 放在中文系统字体前面：拉丁字母和数字用 Figtree，中文自动回退到系统字体。

## 排版规则

- 数字一律 `font-variant-numeric: tabular-nums`（Tailwind `tabular-nums`），表格数字列再用等宽字体。
- 行高：中文正文 1.75，英文段落 1.6，对话正文 16px / 1.75。
- 中英文之间不手动加空格也能读，但文案里建议加一个半角空格（例如“约 4200 词”）。
- 字号阶梯：Display 48/56·700，H1 28/36·650，H2 20/28·650，卡片标题 16/24·600，正文 15/26，对话 16/28，Small 13/21，XS 12/18，Stat 32/36·650，Micro 10（AI 标记）。手机上 H1 22、Display 34、Stat 26。
