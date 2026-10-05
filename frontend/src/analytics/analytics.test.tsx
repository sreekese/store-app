import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import Reports from "./Reports";
import { TrackView } from "./tracking";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
const state = vi.hoisted(() => ({ role: "MERCHANT" as string | null }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: state.role ? { id: "u1", role: state.role } : null }),
}));
const api = vi.mocked(authorized);
const data = {
  scope: "merchant",
  timezone: "Asia/Kolkata",
  generated_at: "2026-10-05T00:00:00Z",
  as_of: "2026-10-05T00:00:00Z",
  start_date: "2026-09-06",
  end_date: "2026-10-05",
  summary: {
    claims: 7,
    redemptions: 3,
    cohort_rate: "28.57",
    engaged_shoppers: 4,
  },
  retention: {
    previous_start_date: "2026-08-07",
    previous_end_date: "2026-09-05",
    previous_active_merchants: 1,
    retained_merchants: 1,
    rate: "100.00",
  },
  daily: [
    { date: "2026-10-05", claims: 7, redemptions: 3, engaged_shoppers: 4 },
  ],
  events: [{ kind: "COUPON_CLAIMED", count: 7 }],
  campaigns: { items: [], next_offset: null },
  merchants: { items: [], next_offset: null },
};
beforeEach(() => {
  vi.resetAllMocks();
  state.role = "MERCHANT";
  api.mockResolvedValue(data);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function setup() {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false, gcTime: 0 } },
          })
        }
      >
        <Reports />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
it("explains cohort metrics and restricts merchant controls", async () => {
  setup();
  await screen.findByText("COUPON_CLAIMED");
  expect(screen.getByText(/Conversion counts coupons/)).toBeInTheDocument();
  expect(
    screen.queryByText("Platform payment movement"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Business reference (optional)"),
  ).not.toBeInTheDocument();
});
it("applies edited dates explicitly and disables export while dirty", async () => {
  setup();
  await screen.findByText("COUPON_CLAIMED");
  const count = api.mock.calls.length;
  fireEvent.change(screen.getByLabelText("Start date"), {
    target: { value: "2026-09-01" },
  });
  expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();
  expect(api.mock.calls.length).toBe(count);
  fireEvent.click(screen.getByRole("button", { name: "Apply dates" }));
  await waitFor(() =>
    expect(
      api.mock.calls.some(([p]) => p.includes("start_date=2026-09-01")),
    ).toBe(true),
  );
});
it("hides cached report after refresh failure", async () => {
  setup();
  await screen.findByText("COUPON_CLAIMED");
  api.mockRejectedValue(new Error("Report unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh report" }));
  await screen.findByText("Report unavailable");
  expect(screen.queryByText("COUPON_CLAIMED")).not.toBeInTheDocument();
});
it("labels sandbox payment movement for superadmin", async () => {
  state.role = "SUPER_ADMIN";
  api.mockResolvedValue({
    ...data,
    revenue: [
      {
        provider: "sandbox",
        currency: "INR",
        gross_minor: 12000,
        refund_minor: 12000,
        net_minor: 0,
        payments: 1,
      },
    ],
  });
  setup();
  await screen.findByText("Platform payment movement");
  expect(screen.getByText(/Sandbox rows are simulated/)).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "revenue" })).toBeInTheDocument();
});
it("downloads selected CSV using applied filters", async () => {
  const create = vi.fn().mockReturnValue("blob:test");
  Object.defineProperty(URL, "createObjectURL", {
    value: create,
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: vi.fn(),
    configurable: true,
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  api.mockImplementation(async (p) =>
    p.startsWith("/analytics/export") ? "date,claims\n2026-10-05,7\n" : data,
  );
  setup();
  await screen.findByText("COUPON_CLAIMED");
  fireEvent.change(screen.getByLabelText("Export report"), {
    target: { value: "campaigns" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Download CSV" }));
  await waitFor(() => expect(create).toHaveBeenCalled());
  expect(
    api.mock.calls.some(
      ([p]) => p.includes("/analytics/export?") && p.includes("kind=campaigns"),
    ),
  ).toBe(true);
});
it("shows export errors", async () => {
  api.mockImplementation(async (p) => {
    if (p.startsWith("/analytics/export")) throw new Error("Export too large");
    return data;
  });
  setup();
  await screen.findByText("COUPON_CLAIMED");
  fireEvent.click(screen.getByRole("button", { name: "Download CSV" }));
  expect(await screen.findByText("Export too large")).toBeInTheDocument();
});
it("tracks an intersecting shopper view once", () => {
  state.role = "USER";
  api.mockResolvedValue(undefined);
  let notify: (entries: { isIntersecting: boolean }[]) => void = () => {};
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: typeof notify) {
        notify = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  render(<TrackView kind="STORE_VIEWED" id="store1" />);
  notify([{ isIntersecting: false }]);
  expect(api).not.toHaveBeenCalled();
  notify([{ isIntersecting: true }]);
  notify([{ isIntersecting: true }]);
  expect(api).toHaveBeenCalledTimes(1);
});
it.each([null, "MERCHANT", "ADMIN", "SUPER_ADMIN"])(
  "does not track %s viewers",
  (role) => {
    state.role = role;
    const observer = vi.fn();
    vi.stubGlobal("IntersectionObserver", observer);
    render(<TrackView kind="STORE_VIEWED" id="store1" />);
    expect(observer).not.toHaveBeenCalled();
    expect(api).not.toHaveBeenCalled();
  },
);
it("filters platform reports by selecting a business name", async () => {
  state.role = "ADMIN";
  api.mockResolvedValue({
    ...data,
    merchants: {
      items: [
        {
          id: "business1",
          business_name: "Local Cafe",
          status: "VERIFIED",
          claims: 7,
          redemptions: 3,
        },
      ],
      next_offset: null,
    },
  });
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Local Cafe" }));
  await waitFor(() =>
    expect(
      api.mock.calls.some(([path]) => path.includes("merchant_id=business1")),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Show all businesses" }));
  await waitFor(() =>
    expect(api.mock.calls.at(-1)?.[0]).not.toContain("merchant_id="),
  );
});
