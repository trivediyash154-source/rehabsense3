"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { MotionConfig } from "framer-motion";
import { Sun, Moon, Monitor } from "lucide-react";
import { themeKey, themeLabels, type Theme, type ThemePreference } from "@/lib/theme";
import { safeRoute, track } from "@/lib/analytics";
import { storePreference } from "@/lib/consent";

type ThemeContextValue = {
  theme: Theme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  /** True once the client has read stored preferences; avoids hydration drift. */
  ready: boolean;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  preference: "system",
  setPreference: () => undefined,
  ready: false,
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function Providers({ children }: { children: ReactNode }) {
  // The inline boot script has already stamped data-theme before hydration.
  // Server render assumes "dark"; the first effect reconciles with reality.
  const [theme, setTheme] = useState<Theme>("dark");
  const [preference, updatePreference] = useState<ThemePreference>("system");
  const [ready, setReady] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(themeKey);
    } catch {
      // Storage can be unavailable (private mode, blocked cookies).
    }
    updatePreference(stored === "dark" || stored === "light" ? stored : "system");
    setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const next: Theme =
        preference === "system" ? (media.matches ? "dark" : "light") : preference;
      const root = document.documentElement;
      // Suppress transitions during the swap so it reads as a deliberate cut,
      // not a slow smear of every element on the page.
      root.dataset.themeSwitching = "true";
      root.dataset.theme = next;
      root.style.colorScheme = next;
      setTheme(next);
      window.setTimeout(() => delete root.dataset.themeSwitching, 90);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [preference, ready]);

  useEffect(() => {
    const route = safeRoute(pathname);
    if (route) track("page_view", { route });
  }, [pathname]);

  const setPreference = useCallback((next: ThemePreference) => {
    updatePreference(next);
    // Remembered on this device only with preference consent (lib/consent);
    // otherwise it applies to this visit and is not written down.
    storePreference(themeKey, next === "system" ? null : next);
    track("theme_changed", {
      theme:
        next === "system"
          ? matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light"
          : next,
    });
  }, []);

  const value = useMemo(
    () => ({ theme, preference, setPreference, ready }),
    [theme, preference, setPreference, ready],
  );

  return (
    <ThemeContext.Provider value={value}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </ThemeContext.Provider>
  );
}

export function ThemeToggle({ systemOption = false }: { systemOption?: boolean }) {
  const { theme, preference, setPreference } = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className="theme-controls">
      <button
        className="icon-button"
        type="button"
        onClick={() => setPreference(next)}
        aria-label={`Switch to ${themeLabels[next]} theme`}
        title={`${themeLabels[theme]} — switch to ${themeLabels[next]}`}
      >
        {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      </button>
      {systemOption && (
        <button
          className={`icon-button ${preference === "system" ? "selected" : ""}`}
          type="button"
          onClick={() => setPreference("system")}
          aria-label="Follow system theme"
          aria-pressed={preference === "system"}
          title="Follow system theme"
        >
          <Monitor size={17} />
        </button>
      )}
    </div>
  );
}
