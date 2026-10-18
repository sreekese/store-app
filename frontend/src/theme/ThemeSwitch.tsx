import { useEffect, useState } from "react";
const key = "nearperk-theme";
type Theme = "light" | "dark";
function saved(): Theme | null {
  try {
    const value = localStorage.getItem(key);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}
export default function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(
    () =>
      saved() ??
      (window.matchMedia?.("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"),
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#101d19" : "#24684c");
  }, [theme]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key !== key && event.key !== null) return;
      setTheme(
        saved() ??
          (window.matchMedia?.("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light"),
      );
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return (
    <>
      <button
        className="theme-switch"
        type="button"
        aria-label="Dark mode"
        title={
          theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
        }
        aria-pressed={theme === "dark"}
        onClick={() => {
          const next = theme === "dark" ? "light" : "dark";
          setTheme(next);
          try {
            localStorage.setItem(key, next);
          } catch {
            /* The toggle still works without storage. */
          }
        }}
      >
        <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      </button>
    </>
  );
}
