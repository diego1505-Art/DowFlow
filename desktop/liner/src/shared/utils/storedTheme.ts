export function applyStoredTheme(): void {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem("theme");
  } catch {}
  const theme =
    stored === "light" || stored === "dark"
      ? stored
      : window.matchMedia?.("(prefers-color-scheme: dark)")?.matches
        ? "dark"
        : "light";
  const root = document.documentElement;
  root.classList.add("app-window");
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
}
