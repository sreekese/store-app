import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ThemeSwitch from "./ThemeSwitch";
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.colorScheme = "";
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("switches both ways and remembers the choice after remount", () => {
  const view = render(<ThemeSwitch />);
  fireEvent.click(screen.getByRole("button", { name: "Dark mode" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("nearperk-theme")).toBe("dark");
  view.unmount();
  render(<ThemeSwitch />);
  expect(screen.getByRole("button", { name: "Dark mode" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Dark mode" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});
it("uses device preference unless an explicit choice exists", () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  const view = render(<ThemeSwitch />);
  expect(document.documentElement.dataset.theme).toBe("dark");
  view.unmount();
  localStorage.setItem("nearperk-theme", "light");
  render(<ThemeSwitch />);
  expect(document.documentElement.dataset.theme).toBe("light");
});
it("still switches when storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw Error("Blocked");
  });
  render(<ThemeSwitch />);
  fireEvent.click(screen.getByRole("button", { name: "Dark mode" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});
it("syncs a choice from another tab", () => {
  render(<ThemeSwitch />);
  localStorage.setItem("nearperk-theme", "dark");
  fireEvent(
    window,
    new StorageEvent("storage", { key: "nearperk-theme", newValue: "dark" }),
  );
  expect(document.documentElement.dataset.theme).toBe("dark");
});
