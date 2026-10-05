import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { clearAccessToken, restoreSession } from "./auth/client";
import { safeReturnTo, type Role } from "./auth/types";
vi.mock("./offers/OfferBrowser", () => ({ default: () => null }));
const user = (role: Role = "USER") => ({
  id: "user-1",
  email: "ananya@example.com",
  display_name: "Ananya",
  role,
});
const result = (role: Role = "USER") => ({
  access_token: "memory-only-token",
  expires_in: 900,
  token_type: "bearer",
  user: user(role),
});
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers({ "Content-Type": "application/json" }),
  json: async () => data,
});
function setup(path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function mockFetch(role: Role | null = null, loginFails = false) {
  const fn = vi.fn(async (input: string, options?: RequestInit) => {
    if (input.endsWith("/auth/refresh"))
      return role
        ? response(result(role))
        : response({ error: { message: "Sign in" } }, 401);
    if (input.endsWith("/locations/config"))
      return response({ default_radius_km: 5, max_radius_km: 10 });
    if (input.endsWith("/api/v1/status"))
      return response({
        name: "Nearperk",
        version: "0.2.0",
        sprint: 1,
        stage: "authentication",
      });
    if (input.endsWith("/auth/login")) {
      if (loginFails)
        return response(
          {
            error: {
              message: "Email or password is incorrect for this workspace.",
            },
          },
          401,
        );
      const data = JSON.parse(options?.body as string);
      return response(result(data.workspace));
    }
    if (input.includes("/campaigns?") || input.includes("/shopper/claims?"))
      return response([]);
    if (input.endsWith("/categories") || input.includes("/admin/offers?"))
      return response([]);
    if (input.endsWith("/merchant/offers/config"))
      return response({ moderation_enabled: true });
    if (input.endsWith("/auth/register")) return response(user("USER"), 201);
    if (input.endsWith("/auth/logout")) return response(null, 204);
    if (input.endsWith("/merchant/profile")) return response(null);
    if (input.endsWith("/profile"))
      return response({
        ...user(),
        phone: "",
        city: "",
        area: "",
        postal_code: "",
        location_preference: "MANUAL",
      });
    if (input.endsWith("/staff/stores") || input.includes("/admin/merchants?"))
      return response([]);
    if (input.includes("/workspaces/")) return response(user(role || "USER"));
    throw new Error("Unexpected request " + input);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
beforeEach(() => clearAccessToken());
afterEach(() => vi.unstubAllGlobals());
describe("Sprint 1 account flows", () => {
  it("waits for session restoration before choosing the shopper experience", async () => {
    let finish!: (value: ReturnType<typeof response>) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/auth/refresh")
          ? new Promise((resolve) => {
              finish = resolve;
            })
          : Promise.resolve(
              response({ name: "Nearperk", version: "0.2.0", sprint: 1 }),
            ),
      ),
    );
    setup();
    expect(screen.getByText("Checking your session…")).toBeInTheDocument();
    await act(async () => {
      finish(response({}, 401));
      await restoreSession();
    });
  });
  it("shows real platform metadata", async () => {
    mockFetch();
    setup();
    expect(await screen.findByText("● API connected")).toBeInTheDocument();
  });
  it.each([
    ["/login", "Shopper"],
    ["/merchant/login", "Store admin"],
    ["/staff/login", "Staff"],
    ["/admin/login", "Admin"],
    ["/superadmin/login", "Superadmin"],
  ])("renders separate login %s", async (path, label) => {
    mockFetch();
    setup(path);
    expect(
      await screen.findByRole("heading", { name: label + " sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toBeInTheDocument();
    expect(screen.queryByRole("contentinfo")).not.toBeInTheDocument();
  });
  it("redirects anonymous protected navigation to the correct login", async () => {
    mockFetch();
    setup("/staff/redeem");
    expect(
      await screen.findByRole("heading", { name: "Staff sign in" }),
    ).toBeInTheDocument();
  });
  it("blocks a shopper from a privileged workspace", async () => {
    const fetch = mockFetch("USER");
    setup("/superadmin/dashboard");
    expect(
      await screen.findByText(
        "This workspace isn’t available to your account.",
      ),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.some(([url]) => url.includes("/workspaces/superadmin")),
    ).toBe(false);
  });
  it("restores a session and verifies workspace access on the server", async () => {
    const fetch = mockFetch("MERCHANT");
    setup("/merchant/dashboard");
    expect(
      await screen.findByText("Your account is ready."),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.some(
        ([url, options]) =>
          url.endsWith("/workspaces/merchant") &&
          (options?.headers as Record<string, string>).Authorization ===
            "Bearer memory-only-token",
      ),
    ).toBe(true);
  });
  it("submits credentials and enters the shopper workspace", async () => {
    const fetch = mockFetch();
    setup("/login");
    await screen.findByLabelText("Email address");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sign in →" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "ananya@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "long-enough-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in →" }));
    expect(
      await screen.findByText("Your account is ready."),
    ).toBeInTheDocument();
    const payload = fetch.mock.calls.find(([url]) =>
      url.endsWith("/auth/login"),
    )?.[1]?.body;
    expect(JSON.parse(payload as string).workspace).toBe("USER");
    expect(localStorage.getItem("access_token")).toBeNull();
  });
  it("shows credential errors without navigating", async () => {
    mockFetch(null, true);
    setup("/merchant/login");
    await screen.findByLabelText("Email address");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sign in →" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in →" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Email or password is incorrect",
    );
  });
  it("registers shopper then signs in", async () => {
    const fetch = mockFetch();
    setup("/register");
    await screen.findByLabelText("Full name");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Create account →" }),
      ).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Ananya" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "ananya@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/Password/), {
      target: { value: "long-enough-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account →" }));
    expect(
      await screen.findByText("Your account is ready."),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.some(([url]) => url.endsWith("/auth/register")),
    ).toBe(true);
  });
  it("logs out and removes protected content", async () => {
    mockFetch("USER");
    setup("/app");
    await screen.findByText("Your account is ready.");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(
      await screen.findByRole("heading", { name: "Shopper sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Your account is ready."),
    ).not.toBeInTheDocument();
  });
  it("clears private content when another tab signs out", async () => {
    mockFetch("USER");
    setup("/app");
    await screen.findByText("Your account is ready.");
    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "nearperk-session-event",
          newValue: "logout:other-tab",
        }),
      );
    });
    expect(
      await screen.findByRole("heading", { name: "Shopper sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Your account is ready."),
    ).not.toBeInTheDocument();
  });
  it("keeps the session visible when server logout fails", async () => {
    const fetch = mockFetch("USER");
    setup("/app");
    await screen.findByText("Your account is ready.");
    fetch.mockImplementationOnce(async () =>
      response({ error: { message: "Sign out temporarily unavailable" } }, 503),
    );
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign out temporarily unavailable",
    );
    expect(screen.getByText("Your account is ready.")).toBeInTheDocument();
  });
  it("shows a recovery state instead of granting access when session check fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    setup("/app");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Check your connection",
    );
  });
  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/superadmin/dashboard",
    "/app/../../superadmin/dashboard",
  ])("rejects unsafe return destination %s", (url) => {
    expect(safeReturnTo("USER", url)).toBe("/app");
  });
  it("preserves a safe selected offer after login", () => {
    expect(safeReturnTo("USER", "/offers/offer-123?source=home")).toBe(
      "/offers/offer-123?source=home",
    );
  });
});

it.each(["MERCHANT", "MERCHANT_STAFF", "ADMIN", "SUPER_ADMIN"] as Role[])(
  "redirects %s away from shopper discovery",
  async (role) => {
    mockFetch(role);
    setup("/");
    expect(
      await screen.findByRole("heading", { name: "Your account is ready." }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Good things are closer."),
    ).not.toBeInTheDocument();
  },
);

it("restores only safe shopper wallet return paths", () => {
  expect(safeReturnTo("USER", "/app/coupons/abc-123")).toBe(
    "/app/coupons/abc-123",
  );
  expect(safeReturnTo("USER", "/app/coupons?status=EXPIRED")).toBe(
    "/app/coupons?status=EXPIRED",
  );
  expect(safeReturnTo("MERCHANT", "/app/coupons/abc-123")).toBe(
    "/merchant/dashboard",
  );
  expect(safeReturnTo("USER", "//evil.example/app/coupons")).toBe("/app");
});
it("wallet deep links require shopper login", async () => {
  mockFetch();
  setup("/app/coupons/abc-123");
  expect(
    await screen.findByRole("heading", { name: "Shopper sign in" }),
  ).toBeInTheDocument();
});
