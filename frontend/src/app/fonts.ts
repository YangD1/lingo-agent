import localFont from "next/font/local";

// Self-hosted so builds never reach out to Google Fonts. The text face, LXGW
// WenKai, is sliced by unicode-range in wenkai.css (ADR 0059), not loaded here.
export const geistMono = localFont({
  src: "../fonts/geist-mono-latin-wght.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
});
