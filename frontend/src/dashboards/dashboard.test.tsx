import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import type { Role } from "../auth/types";
import Dashboard from "./Dashboard";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
const api = vi.mocked(authorized);
const result = {
  scope: "merchant",
  generated_at: "2026-09-28T07:00:00Z",
  timezone: "Asia/Kolkata",
  days: 7,
  start_date: "2026-09-22",
  end_date: "2026-09-28",
  totals: {
    claims: 4,
    redemptions: 1,
    active_coupons: 2,
    redemption_rate: "25.00",
    recorded_purchase_amount: "250.00",
    coupon_benefit_amount: "50.00",
  },
  daily: [{ date: "2026-09-28", claims: 4, redemptions: 1 }],
  top_offers: [{ offer_id: "one", title: "Lunch special", claims: 4 }],
};
function setup(role: Role = "MERCHANT") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <Dashboard role={role} />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.mockResolvedValue(result);
});
it("shows server totals, amount definitions and accessible daily counts", async () => {
  setup();
  expect(await screen.findByText("25.00%")).toBeInTheDocument();
  expect(screen.getByText("₹250.00")).toBeInTheDocument();
  expect(
    screen.getByText(/not verified revenue or payments/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByText("View daily counts"));
  expect(screen.getByRole("table")).toHaveTextContent("2026-09-28");
  expect(screen.getByText("Lunch special")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/dashboards/merchant?days=30");
});
it("changes bounded chart periods and refreshes metrics", async () => {
  setup();
  await screen.findByText("25.00%");
  fireEvent.change(screen.getByLabelText("Chart period"), {
    target: { value: "7" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/dashboards/merchant?days=7"),
  );
  await waitFor(() =>
    expect(screen.getByText("Refresh metrics")).not.toBeDisabled(),
  );
  const before = api.mock.calls.length;
  fireEvent.click(screen.getByText("Refresh metrics"));
  await waitFor(() => expect(api.mock.calls.length).toBeGreaterThan(before));
});
it("shows pending and empty results without fabricated activity", async () => {
  let finish!: (value: unknown) => void;
  api.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  setup();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Loading activity metrics",
  );
  finish({
    ...result,
    totals: { claims: 0, redemption_rate: null },
    daily: [],
    top_offers: [],
  });
  expect(
    await screen.findByText("No activity in this period."),
  ).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
});
it("hides stale totals after access failure and supports retry", async () => {
  const client = setup();
  await screen.findByText("25.00%");
  api.mockRejectedValueOnce(new Error("Access denied"));
  await client.invalidateQueries({ queryKey: ["dashboard"] });
  expect(await screen.findByRole("alert")).toHaveTextContent("Access denied");
  expect(screen.queryByText("25.00%")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Retry metrics"));
  expect(await screen.findByText("25.00%")).toBeInTheDocument();
});
it.each(["ADMIN", "SUPER_ADMIN"] as Role[])(
  "routes %s to platform metrics",
  async (role) => {
    setup(role);
    await screen.findByText("25.00%");
    expect(api).toHaveBeenCalledWith("/dashboards/platform?days=30");
    expect(screen.getByText("Platform overview")).toBeInTheDocument();
  },
);
it("limits the staff presentation to personal counter activity", async () => {
  api.mockResolvedValue({
    ...result,
    totals: { assigned_branches: 1, redemptions: 1 },
    daily: [{ date: "2026-09-28", redemptions: 1 }],
    top_offers: [],
  });
  setup("MERCHANT_STAFF");
  expect(await screen.findByText("Assigned branches")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/dashboards/staff?days=30");
  expect(screen.queryByText("Coupons claimed")).not.toBeInTheDocument();
  expect(screen.queryByText(/Top offers by claims/)).not.toBeInTheDocument();
});
