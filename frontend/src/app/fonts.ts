import localFont from "next/font/local";

// Self-hosted so builds never reach out to Google Fonts. Latin subset only:
// Chinese falls through to the system stack in globals.css (--font-sans).
export const figtree = localFont({
  src: "../fonts/figtree-latin-wght.woff2",
  weight: "300 900",
  variable: "--font-figtree",
  display: "swap",
});

export const geistMono = localFont({
  src: "../fonts/geist-mono-latin-wght.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
});
