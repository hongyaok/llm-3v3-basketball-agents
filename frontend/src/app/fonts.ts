import localFont from "next/font/local";

export const switzer = localFont({
  src: [
    { path: "../fonts/switzer-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../fonts/switzer-500-normal.woff2", weight: "500", style: "normal" },
    { path: "../fonts/switzer-600-normal.woff2", weight: "600", style: "normal" },
    { path: "../fonts/switzer-700-normal.woff2", weight: "700", style: "normal" },
    { path: "../fonts/switzer-400-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-switzer",
  display: "swap",
});

export const zodiak = localFont({
  src: [
    { path: "../fonts/zodiak-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../fonts/zodiak-400-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-zodiak",
  display: "swap",
});

export const jetBrainsMono = localFont({
  src: [
    { path: "../fonts/jetbrains-mono-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../fonts/jetbrains-mono-500-normal.woff2", weight: "500", style: "normal" },
    { path: "../fonts/jetbrains-mono-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

