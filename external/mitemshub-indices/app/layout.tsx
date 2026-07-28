import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "MitemsHub Indices",
  description: "Private operator workspace for synthetic indices calls.",
  icons: { icon: "/favicon.ico" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#efeae0" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1217" },
  ],
};

/**
 * Minimal inline script to prevent a flash of the wrong theme.
 * Runs before React hydrates — reads localStorage (or system pref)
 * and sets `data-theme` on the root <html> element immediately.
 *
 * Handles three stored values:
 *   "light" / "dark"  — explicit manual override
 *   "auto" / missing — follows the OS `prefers-color-scheme`
 */
const themeScript = `
(function() {
  try {
    var stored = localStorage.getItem("mitems-theme");
    var theme;
    if (stored === "light" || stored === "dark") {
      theme = stored;
    } else {
      theme = "light";
    }
    document.documentElement.setAttribute("data-theme", theme);
  } catch(e) {}
})();
`;

/**
 * Second inline script — runs after the first paint so the initial
 * render has zero transition delay. After this script executes, the
 * html element gets `transition: background 400ms ease, color 300ms ease`
 * so that any subsequent theme toggle animates smoothly.
 */
const transitionScript = `
(function() {
  try {
    requestAnimationFrame(function() {
      document.documentElement.style.transition = "background 400ms ease, color 300ms ease";
      document.body.classList.add("theme-entrance");
    });
  } catch(e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <script dangerouslySetInnerHTML={{ __html: transitionScript }} />
      </head>
      <body suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}