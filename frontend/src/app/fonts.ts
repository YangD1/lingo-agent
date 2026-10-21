import localFont from "next/font/local";

// Self-hosted so builds never reach out to Google Fonts. The text font is picked per
// browser and loaded from public/fonts/ by the boot script in layout.tsx (ADR 0060).
export const geistMono = localFont({
  src: "../fonts/geist-mono-latin-wght.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
});
