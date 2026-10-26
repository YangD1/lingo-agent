import localFont from "next/font/local";

// The word wall's face (ADR 0065 §6). Imported only by the home page, so no other page
// preloads it. Variable in width and weight: the wall uses 200–900 at 100–112% width.
export const archivo = localFont({
  src: "../../fonts/archivo-latin-wdth-wght.woff2",
  weight: "100 900",
  variable: "--font-archivo",
  display: "swap",
  declarations: [{ prop: "font-stretch", value: "62% 125%" }],
});
