// Light (baby blue + orange) or dark (night sky blue + orange). The choice is stored per browser;
// until the user picks one, the app follows the system setting. index.html applies it before first
// paint so the page never flashes the wrong theme.
import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "tekt.theme";
const query = () => window.matchMedia("(prefers-color-scheme: dark)");

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export const initialTheme = (): Theme => stored() ?? (query().matches ? "dark" : "light");

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => applyTheme(theme), [theme]);

  // Follow the system until the user chooses.
  useEffect(() => {
    const q = query();
    const follow = (e: MediaQueryListEvent) => !stored() && setTheme(e.matches ? "dark" : "light");
    q.addEventListener("change", follow);
    return () => q.removeEventListener("change", follow);
  }, []);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage unavailable: the choice lasts for this page only */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
