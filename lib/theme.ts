export type Theme = "dark" | "light";
export type ThemePreference = Theme | "system";

export const themeKey = "rehabsense-theme";

export const themeLabels: Record<Theme, string> = {
  dark: "Night Lab",
  light: "Clinical Daylight",
};

/**
 * Runs before paint so the first frame is already in the correct theme.
 * Kept dependency-free and failure-tolerant: private-mode storage access can
 * throw, and the page must still render.
 */
export const themeBootScript = `
try {
  var p = localStorage.getItem('${themeKey}');
  var t = p === 'light' || p === 'dark'
    ? p
    : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = t;
  document.documentElement.style.colorScheme = t;
} catch (e) {
  document.documentElement.dataset.theme = 'dark';
  document.documentElement.style.colorScheme = 'dark';
}
`;
