import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { authorized, raw } from "../auth/client";
import ClaimCoupons, { ClaimReceipts } from "./ClaimCoupons";
import Campaigns from "./Campaigns";
import type { Role } from "../auth/types";
vi.mock("../auth/client", () => ({ authorized: vi.fn(), raw: vi.fn() }));
const session = vi.hoisted(() => ({
  user: null as { id: string; role: Role } | null,
}));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => session }));
const api = vi.mocked(authorized),
  pub = vi.mocked(raw);
const campaign = {
  id: "c1",
  offer_id: "o1",
  title: "Lunch coupon",
  store_ids: ["s1"],
  total_quantity: 10,
  claimed_count: 0,
  available_count: 10,
  per_user_limit: 1,
  validity_hours: 2,
  starts_at: "2026-09-01T09:00:22Z",
  expires_at: "2027-01-01T09:00:33Z",
  status: "ACTIVE",
  revision: 2,
};
const allowance = {
  remaining: 1,
  used: 0,
  limit: 1,
  resets_at: "2027-01-02T18:30:00Z",
  timezone: "Asia/Kolkata",
};
const receipt = {
  id: "receipt1",
  campaign_id: "c1",
  title: "Lunch coupon",
  status: "CLAIMED",
  expires_at: "2027-01-01T10:00:00Z",
};
function setup(node: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  session.user = { id: "u1", role: "USER" };
  api.mockReset();
  pub.mockReset();
  pub.mockResolvedValue([campaign]);
  api.mockResolvedValue(allowance);
});
it("guest claim action restores the selected offer after login", async () => {
  session.user = null;
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  expect(
    await screen.findByRole("link", { name: "Sign in to claim" }),
  ).toHaveAttribute("href", "/login?returnTo=%2Foffers%2Fo1%3Fstore_id%3Ds1");
  expect(api).not.toHaveBeenCalled();
});
it("claim uses a request key and updates saved receipt and allowance", async () => {
  api.mockImplementation(async (path) =>
    path.includes("/claim") ? receipt : allowance,
  );
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Claim coupon" }));
  expect(
    await screen.findByText("Coupon claimed: Lunch coupon"),
  ).toBeInTheDocument();
  const call = api.mock.calls.find(([p]) => p.endsWith("/claim"))!;
  expect(call[1]?.method).toBe("POST");
  expect(
    (call[1]?.headers as Record<string, string>)["Idempotency-Key"],
  ).toMatch(/^[0-9a-f-]{36}$/);
  expect(
    screen.getByText(/Claiming uses one daily allowance/),
  ).toBeInTheDocument();
});
it("retry after an ambiguous network failure reuses the request key", async () => {
  let tries = 0;
  api.mockImplementation(async (path) => {
    if (path.endsWith("/claim")) {
      if (++tries === 1) throw new Error("Network interrupted");
      return receipt;
    }
    return allowance;
  });
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Claim coupon" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Network interrupted",
  );
  fireEvent.click(screen.getByRole("button", { name: "Claim coupon" }));
  expect(
    await screen.findByText("Coupon claimed: Lunch coupon"),
  ).toBeInTheDocument();
  const calls = api.mock.calls.filter(([p]) => p.endsWith("/claim"));
  expect(calls[0][1]?.headers).toEqual(calls[1][1]?.headers);
});
it("used allowance disables claims and shows the reset time", async () => {
  api.mockResolvedValue({ ...allowance, remaining: 0, used: 1 });
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  expect(
    await screen.findByRole("button", { name: "Claim coupon" }),
  ).toBeDisabled();
  expect(screen.getByText(/0 of 1 daily claims remaining/)).toBeInTheDocument();
});
it("empty campaign list does not promise a guaranteed coupon", async () => {
  pub.mockResolvedValue([]);
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  expect(await screen.findByText(/No claimable coupons/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Claim coupon" }),
  ).not.toBeInTheDocument();
});
it("unavailable allowance prevents a claim and offers recovery", async () => {
  api.mockRejectedValue(new Error("Allowance unavailable"));
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Allowance unavailable",
  );
  expect(screen.getByRole("button", { name: "Claim coupon" })).toBeDisabled();
});
it("management roles never receive shopper claim controls", () => {
  session.user = { id: "m1", role: "MERCHANT" };
  setup(<ClaimCoupons offerId="o1" storeId="s1" />);
  expect(
    screen.queryByRole("heading", { name: "Available coupons" }),
  ).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});
it("saved claim receipts recover across navigation without exposing tokens", async () => {
  api.mockResolvedValue([receipt]);
  setup(<ClaimReceipts />);
  expect(await screen.findByText("Lunch coupon")).toBeInTheDocument();
  expect(screen.getByText("Reference: receipt1")).toBeInTheDocument();
  expect(screen.queryByText(/claim_token/)).not.toBeInTheDocument();
});
function management() {
  api.mockImplementation(async (path, options) => {
    if (options?.method) return campaign;
    if (path.includes("/merchant/offers?"))
      return [{ ...campaign, id: "o1", store_id: null, title: "Lunch offer" }];
    if (path === "/merchant/stores")
      return [{ id: "s1", name: "Central", status: "ACTIVE" }];
    if (path.includes("/campaigns?")) return [campaign];
    throw new Error("Unexpected path");
  });
}
it("merchant creation requires explicit branches and preserves exact offer dates", async () => {
  management();
  setup(<Campaigns />);
  fireEvent.click(screen.getByRole("button", { name: "Create campaign" }));
  fireEvent.change(await screen.findByLabelText("Offer"), {
    target: { value: "o1" },
  });
  expect(screen.getByRole("button", { name: "Save campaign" })).toBeDisabled();
  fireEvent.click(screen.getByLabelText("Central"));
  fireEvent.click(screen.getByRole("button", { name: "Save campaign" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/merchant/campaigns",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const data = JSON.parse(
    api.mock.calls.find(
      ([p, o]) => p === "/merchant/campaigns" && o?.method === "POST",
    )![1]!.body as string,
  );
  expect(data.store_ids).toEqual(["s1"]);
  expect(data.starts_at).toBe(campaign.starts_at);
  expect(data.expires_at).toBe(campaign.expires_at);
  expect(data).not.toHaveProperty("claimed_count");
});
it("pause action sends the current revision", async () => {
  management();
  setup(<Campaigns />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Pause campaign" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/merchant/campaigns/c1/actions",
      expect.objectContaining({
        body: JSON.stringify({ revision: 2, action: "PAUSE" }),
      }),
    ),
  );
});
it("admin oversight contains no merchant creation or shopper claim controls", async () => {
  management();
  setup(<Campaigns admin />);
  expect(await screen.findByText("Lunch coupon")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Create campaign" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Claim coupon" }),
  ).not.toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/admin/campaigns?offset=0");
});

it("successful claims open the matching private wallet detail", async () => {
  api.mockImplementation(async (path) =>
    path.endsWith("/claim") ? receipt : allowance,
  );
  setup(
    <Routes>
      <Route path="/" element={<ClaimCoupons offerId="o1" storeId="s1" />} />
      <Route
        path="/app/coupons/receipt1"
        element={<h1>Saved coupon opened</h1>}
      />
    </Routes>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Claim coupon" }));
  expect(
    await screen.findByRole("heading", { name: "Saved coupon opened" }),
  ).toBeInTheDocument();
});
