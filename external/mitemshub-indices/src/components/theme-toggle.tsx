"use client";

import { useEffect, useState, useRef } from "react";

const STORAGE_KEY = "mitems-theme";
type ThemeMode = "light" | "dark" | "auto";
const CYCLE: ThemeMode[] = ["light", "dark", "auto"];

function getStoredMode(): ThemeMode | null {
  try {
    const val = localStorage.getItem(STORAGE_KEY);
    if (val === "light" || val === "dark" || val === "auto") return val;
    return null;
  } catch {
    return null;
  }
}

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyMode(mode: ThemeMode): "light" | "dark" {
  let effective: "light" | "dark";
  if (mode === "auto") {
    effective = getSystemTheme();
    try {
      localStorage.setItem(STORAGE_KEY, "auto");
    } catch {
      // localStorage may be unavailable
    }
  } else {
    effective = mode;
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // localStorage may be unavailable
    }
  }
  document.documentElement.setAttribute("data-theme", effective);
  return effective;
}

/** Sun icon — shown when the current mode is "light"
 *
 * Accepts an optional `pulseKey` — when the key changes (OS preference toggled),
 * the SVG remounts and a rotation-flicker animation plays briefly. */
function SunIcon({ pulseKey }: { pulseKey?: number }) {
  return (
    <svg
      key={pulseKey}
      width="16" height="16" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      className={pulseKey !== undefined && pulseKey > 0 ? "sun-icon" : ""}
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

/** Moon icon — shown when the current mode is "dark"
 *
 * Accepts an optional `pulseKey` — when the key changes (OS preference toggled),
 * the SVG remounts and a brightness-pulse animation plays briefly. */
function MoonIcon({ pulseKey }: { pulseKey?: number }) {
  return (
    <svg
      key={pulseKey}
      width="16" height="16" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      className={pulseKey !== undefined && pulseKey > 0 ? "moon-icon" : ""}
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

/** Display/monitor icon — shown when the current mode is "auto" (follows system)
 *
 * Accepts an optional `pulseKey` — when the key changes (OS preference toggled),
 * the SVG remounts and the CSS auto-pulse animation plays a brief scale + opacity
 * cycle so you can feel the toggle react even without clicking. */
function AutoIcon({ pulseKey }: { pulseKey?: number }) {
  return (
    <svg
      key={pulseKey}
      width="16" height="16" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      className={pulseKey !== undefined && pulseKey > 0 ? "auto-icon" : ""}
    >
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

/**
 * Three-state theme toggle cycling light → dark → auto → light.
 *
 * - **light** / **dark** — explicit manual override stored in localStorage.
 * - **auto** — follows `prefers-color-scheme` without storing; listens for
 *   OS-level changes and animates the transition smoothly.
 *
 * All three icons are always mounted; CSS transitions handle the
 * rotate + opacity swap between them.
 */
function ThemeIcons({ mode, pulseKey }: { mode: ThemeMode; pulseKey: number }) {
  return (
    <>
      {/* Sun — visible in light mode */}
      <span
        aria-hidden={mode !== "light"}
        style={{
          opacity: mode === "light" ? 1 : 0,
          transform: mode === "light"
            ? "rotate(0deg) scale(1)"
            : "rotate(-90deg) scale(0.5)",
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          transition: "transform 400ms ease, opacity 400ms ease",
        }}
      >
        <SunIcon pulseKey={pulseKey} />
      </span>

      {/* Moon — visible in dark mode */}
      <span
        aria-hidden={mode !== "dark"}
        style={{
          opacity: mode === "dark" ? 1 : 0,
          transform: mode === "dark"
            ? "rotate(0deg) scale(1)"
            : "rotate(90deg) scale(0.5)",
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          transition: "transform 400ms ease, opacity 400ms ease",
        }}
      >
        <MoonIcon pulseKey={pulseKey} />
      </span>

      {/* Display icon — visible in auto mode */}
      <span
        aria-hidden={mode !== "auto"}
        style={{
          opacity: mode === "auto" ? 1 : 0,
          transform: mode === "auto"
            ? "rotate(0deg) scale(1)"
            : "rotate(180deg) scale(0.5)",
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          transition: "transform 400ms ease, opacity 400ms ease",
        }}
      >
        <AutoIcon pulseKey={pulseKey} />
      </span>
    </>
  );
}

function resolveLabel(mode: ThemeMode, effective: "light" | "dark"): string {
  if (mode === "auto") {
    return effective === "dark"
      ? "Auto (dark) — cycle to light"
      : "Auto (light) — cycle to dark";
  }
  return mode === "dark"
    ? "Dark — cycle to auto"
    : "Light — cycle to dark";
}

export function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("auto");
  const [effectiveTheme, setEffectiveTheme] = useState<"light" | "dark">("light");
  const [osPulseKey, setOsPulseKey] = useState(0);
  const initialisedRef = useRef(false);

  // Hydrate from stored mode or default to auto on mount
  useEffect(() => {
    if (initialisedRef.current) return;
    initialisedRef.current = true;

    const stored = getStoredMode();
    const initialMode: ThemeMode = stored ?? "auto";
    const effective = applyMode(initialMode);
    setMode(initialMode);
    setEffectiveTheme(effective);
  }, []);

  // Follow system preference when mode is auto
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");

    const handleChange = () => {
      const stored = getStoredMode();
      // Follow system preference when in auto or no stored mode
      if (!stored || stored === "auto") {
        const next = mq.matches ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", next);
        setEffectiveTheme(next);
        setOsPulseKey((k) => k + 1);
      }
    };

    mq.addEventListener("change", handleChange);
    return () => mq.removeEventListener("change", handleChange);
  }, []);

  const toggle = () => {
    const currentIndex = CYCLE.indexOf(mode);
    const nextMode = CYCLE[(currentIndex + 1) % CYCLE.length];
    const effective = applyMode(nextMode);
    setMode(nextMode);
    setEffectiveTheme(effective);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="theme-toggle"
      aria-label={resolveLabel(mode, effectiveTheme)}
      title={resolveLabel(mode, effectiveTheme)}
    >
      <ThemeIcons mode={mode} pulseKey={osPulseKey} />
    </button>
  );
}
