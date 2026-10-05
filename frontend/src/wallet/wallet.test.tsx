import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import Wallet, { CouponDetail } from "./Wallet";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "u1", role: "USER" } }),
}));
const api = vi.mocked(authorized);
const coupon = {
  id: "claim1",
  title: "Saved lunch",
  status: "CLAIMED",
  claimed_at: "2026-01-01T09:00:00Z",
  expires_at: "2026-01-01T12:00:00Z",
  server_time: "2026-01-01T10:00:00Z",
  claim_token: "random-opaque-private-token-no-user-data",
  business_name: "Saved café",
  eligibility: "NEW_CUSTOMER",
  redeemed_at: null,
  availability_message: "Keep this code private.",
  offer: {
    discount_type: "PERCENTAGE",
    discount_value: "20",
    minimum_purchase: "100",
    maximum_discount: "80",
    customer_type: "NEW_CUSTOMERS",
    description: "Saved description",
    terms_conditions: "Original dine-in terms",
  },
  branches: [
    {
      id: "s1",
      name: "Original branch",
      address: "12 Old Road",
      city: "Kochi",
      timezone: "Asia/Kolkata",
      currently_available: true,
      hours: [],
    },
  ],
};
function setup(path = "/app/coupons/claim1") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app/coupons" element={<Wallet />} />
          <Route path="/app/coupons/:id" element={<CouponDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  api.mockReset();
  api.mockResolvedValue(coupon);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("renders a local QR, exact manual token, saved terms and branch details", async () => {
  setup();
  expect(
    await screen.findByRole("heading", { name: "Saved lunch" }),
  ).toBeInTheDocument();
  expect(
    await screen.findByTitle("Private coupon QR code"),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Manual coupon code")).toHaveValue(
    coupon.claim_token,
  );
  expect(screen.getByText("Original dine-in terms")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Original branch" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/12 Old Road/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/shopper/wallet/claim1");
  expect(document.querySelector("img")).toBeNull();
});
it.each(["EXPIRED", "REDEEMED", "CANCELLED"])(
  "never displays codes for %s even if a stale response includes a token",
  async (status) => {
    api.mockResolvedValue({ ...coupon, status });
    setup();
    await screen.findByRole("heading", { name: "Saved lunch" });
    expect(
      screen.queryByTitle("Private coupon QR code"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Manual coupon code"),
    ).not.toBeInTheDocument();
  },
);
it("hides unavailable branch codes while retaining terms", async () => {
  api.mockResolvedValue({
    ...coupon,
    claim_token: null,
    availability_message: "Temporarily unavailable",
    branches: [{ ...coupon.branches[0], currently_available: false }],
  });
  setup();
  expect(
    await screen.findByText("Temporarily unavailable"),
  ).toBeInTheDocument();
  expect(screen.getByText("Original dine-in terms")).toBeInTheDocument();
  expect(screen.queryByTitle("Private coupon QR code")).not.toBeInTheDocument();
});
it("wrong device clock cannot extend the code beyond server expiry", async () => {
  let elapsed = 0;
  vi.spyOn(performance, "now").mockImplementation(() => elapsed);
  api.mockResolvedValue({ ...coupon, expires_at: "2026-01-01T10:00:02Z" });
  setup();
  await screen.findByTitle("Private coupon QR code");
  elapsed = 3000;
  await waitFor(
    () =>
      expect(
        screen.queryByTitle("Private coupon QR code"),
      ).not.toBeInTheDocument(),
    { timeout: 2500 },
  );
  expect(screen.getByText(/This coupon has expired/)).toBeInTheDocument();
});
it("hides codes while the page is backgrounded", async () => {
  setup();
  await screen.findByTitle("Private coupon QR code");
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(screen.queryByTitle("Private coupon QR code")).not.toBeInTheDocument();
});
it("copies only the opaque token after an explicit click", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Copy code" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith(coupon.claim_token),
  );
  expect(
    await screen.findByText("Code copied. Keep it private."),
  ).toBeInTheDocument();
});
it("clipboard failure leaves manual selection available", async () => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("Denied")) },
  });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Copy code" }));
  expect(await screen.findByText(/Select the manual code/)).toBeInTheDocument();
});
it("private detail errors offer retry without showing stale codes", async () => {
  api.mockRejectedValue(new Error("Coupon not found in your wallet."));
  setup();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Coupon not found",
  );
  expect(screen.queryByTitle("Private coupon QR code")).not.toBeInTheDocument();
  api.mockResolvedValue(coupon);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(
    await screen.findByTitle("Private coupon QR code"),
  ).toBeInTheDocument();
});
it("wallet filters reset pagination and never request detail tokens", async () => {
  api.mockResolvedValue({ claims: [coupon], next_offset: 12 });
  setup("/app/coupons");
  expect(
    await screen.findByRole("link", { name: "View coupon" }),
  ).toHaveAttribute("href", "/app/coupons/claim1");
  fireEvent.click(screen.getByRole("button", { name: "More coupons" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/shopper/wallet?status=ACTIVE&offset=12&limit=12",
    ),
  );
  api.mockResolvedValue({ claims: [], next_offset: null });
  fireEvent.click(screen.getByRole("button", { name: "Expired" }));
  expect(
    await screen.findByText("No expired coupons here yet."),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    "/shopper/wallet?status=EXPIRED&offset=0&limit=12",
  );
  expect(screen.queryByLabelText("Manual coupon code")).not.toBeInTheDocument();
});
it("redeemed details show server-confirmed timestamp and reference", async () => {
  api.mockResolvedValue({
    ...coupon,
    status: "REDEEMED",
    claim_token: null,
    redeemed_at: "2026-01-01T11:00:00Z",
  });
  setup();
  expect(
    await screen.findByText(/Redeemed .*Reference: claim1/),
  ).toBeInTheDocument();
});

it("a failed status refresh removes a previously displayed code", async () => {
  setup();
  await screen.findByTitle("Private coupon QR code");
  api.mockRejectedValue(new Error("Session no longer available"));
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Session no longer available",
  );
  expect(screen.queryByTitle("Private coupon QR code")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Manual coupon code")).not.toBeInTheDocument();
});

it("shows the server-confirmed redemption receipt without a QR", async () => {
  api.mockResolvedValue({
    ...coupon,
    status: "REDEEMED",
    claim_token: null,
    redeemed_at: "2026-01-01T11:00:00Z",
    redemption: {
      id: "r1",
      store_name: "Central",
      purchase_amount: "250.00",
      discount_amount: "50.00",
      payable_amount: "200.00",
    },
  });
  setup();
  expect(
    await screen.findByRole("heading", { name: "Redemption receipt" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Recorded eligible purchase ₹250.00/),
  ).toBeInTheDocument();
  expect(screen.queryByTitle("Private coupon QR code")).not.toBeInTheDocument();
});
