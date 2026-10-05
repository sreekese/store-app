import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { authorized } from "../auth/client";
import DailyCoupons from "./DailyCoupons";
import DailyPicks from "./DailyPicks";
import PolicyEditor from "./PolicyEditor";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
const session = vi.hoisted(() => ({
  user: { id: "u1", role: "USER" } as { id: string; role: string } | null,
}));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => session }));
const api = vi.mocked(authorized);
const card = {
  campaign_id: "c1",
  offer_id: "o1",
  store_id: "s1",
  title: "Daily lunch",
  store_name: "Central",
  distance_meters: 200,
};
const result = {
  recommendation: card,
  daily_picks: [],
  next_offset: null,
  allowance: {
    remaining: 1,
    limit: 1,
    period: "DAILY",
    timezone: "Asia/Kolkata",
    resets_at: "2027-01-01T18:30:00Z",
  },
};
const policy = {
  version: 1,
  allowance: 1,
  period: "DAILY",
  timezone: "Asia/Kolkata",
  default_radius_km: 5,
  max_radius_km: 10,
  effective_at: "1970-01-01T00:00:00Z",
};
function setup(child: ReactNode) {
  render(
    <MemoryRouter>
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
        {child}
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  session.user = { id: "u1", role: "USER" };
});
it("loads a recommendation without claiming and sends confirmed coordinates", async () => {
  api.mockResolvedValue(result);
  setup(<DailyCoupons latitude={9} longitude={76} radius={5} />);
  expect(await screen.findByText("Daily lunch")).toBeInTheDocument();
  expect(api).toHaveBeenCalledTimes(1);
  expect(api.mock.calls[0][0]).toBe("/daily/recommendations");
  expect(JSON.parse(api.mock.calls[0][1]!.body as string)).toMatchObject({
    latitude: 9,
    longitude: 76,
    radius_km: 5,
  });
  expect(
    screen.getByRole("link", { name: "Read offer terms" }),
  ).toHaveAttribute("href", "/offers/o1?store_id=s1");
});
it("requires a click to claim and reuses the request key after a failed response", async () => {
  api.mockImplementation(async (path) => {
    if (path.includes("/claim")) throw Error("Connection lost");
    return result;
  });
  setup(<DailyCoupons latitude={9} longitude={76} radius={5} />);
  fireEvent.click(await screen.findByText("Claim this coupon"));
  await screen.findByText("Connection lost");
  await waitFor(() =>
    expect(screen.getByText("Claim this coupon")).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("Claim this coupon"));
  await waitFor(() =>
    expect(api.mock.calls.filter((c) => c[0].includes("/claim"))).toHaveLength(
      2,
    ),
  );
  const calls = api.mock.calls.filter((c) => c[0].includes("/claim"));
  expect(calls[0][1]!.headers).toEqual(calls[1][1]!.headers);
});
it("shows an empty area and exhausted allowance without promising a coupon", async () => {
  api.mockResolvedValue({
    ...result,
    recommendation: null,
    allowance: { ...result.allowance, remaining: 0 },
  });
  setup(<DailyCoupons latitude={0} longitude={0} radius={5} />);
  expect(
    await screen.findByText(/No eligible coupon here today/),
  ).toBeInTheDocument();
  expect(screen.getByText(/0 of 1 daily claims/)).toBeInTheDocument();
});
it("offers sign-in and makes no private requests for guests", () => {
  session.user = null;
  setup(<DailyCoupons latitude={0} longitude={0} radius={5} />);
  expect(screen.getByText("Sign in")).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});
it("requires policy preview and acknowledgement before scheduling", async () => {
  api.mockImplementation(async (path) =>
    path.includes("/history")
      ? { policies: [policy], audit: [] }
      : path.endsWith("/preview")
        ? {
            affected_users: 2,
            effective_at: "2027-01-01T18:30:00Z",
            next_reset: "2027-01-01T18:30:00Z",
            message: "Existing claims are preserved",
            pending_version: null,
          }
        : policy,
  );
  setup(<PolicyEditor />);
  fireEvent.click(await screen.findByText("Prepare policy change"));
  fireEvent.change(
    screen.getByLabelText("Activation timestamp with timezone"),
    { target: { value: "2027-01-02T00:00:00+05:30" } },
  );
  fireEvent.click(screen.getByText("Preview impact"));
  expect(
    await screen.findByText("Existing claims are preserved"),
  ).toBeInTheDocument();
  expect(screen.getByText("Confirm scheduled policy")).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("Confirm scheduled policy"));
  await waitFor(() =>
    expect(api.mock.calls.some((c) => c[0] === "/daily/policy/schedule")).toBe(
      true,
    ),
  );
});
it("editing policy fields invalidates the previous preview", async () => {
  api.mockImplementation(async (path) =>
    path.includes("/history")
      ? { policies: [], audit: [] }
      : path.endsWith("/preview")
        ? {
            affected_users: 0,
            effective_at: "2027-01-01T18:30:00Z",
            next_reset: "2027-01-01T18:30:00Z",
            message: "Preview ready",
            pending_version: null,
          }
        : policy,
  );
  setup(<PolicyEditor />);
  fireEvent.click(await screen.findByText("Prepare policy change"));
  fireEvent.change(
    screen.getByLabelText("Activation timestamp with timezone"),
    { target: { value: "2027-01-02T00:00:00+05:30" } },
  );
  fireEvent.click(screen.getByText("Preview impact"));
  await screen.findByText("Preview ready");
  fireEvent.change(screen.getByLabelText("Claims per period"), {
    target: { value: "2" },
  });
  expect(
    screen.queryByText("Confirm scheduled policy"),
  ).not.toBeInTheDocument();
});
it("saves an explicit no-selection override using current revision", async () => {
  api.mockImplementation(async (path) =>
    path === "/daily/policy"
      ? policy
      : path.includes("/stores?")
        ? [{ id: "s1", name: "Central" }]
        : path.includes("/candidates")
          ? []
          : path.includes("/history")
            ? []
            : {},
  );
  setup(<DailyPicks superadmin />);
  await screen.findByText("Central");
  fireEvent.change(screen.getByLabelText("Daily pick branch"), {
    target: { value: "s1" },
  });
  fireEvent.change(screen.getByLabelText("Business date"), {
    target: { value: "2027-01-01" },
  });
  await waitFor(() =>
    expect(screen.getByText("Save override")).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("Save override"));
  await waitFor(() =>
    expect(api.mock.calls.some((c) => c[1]?.method === "PUT")).toBe(true),
  );
  const call = api.mock.calls.find((c) => c[1]?.method === "PUT")!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    campaign_id: null,
    revision: 0,
  });
});
it("expands an empty coupon search only on explicit request", async () => {
  api.mockResolvedValue({ ...result, recommendation: null });
  const expand = vi.fn();
  setup(
    <DailyCoupons
      latitude={9}
      longitude={76}
      radius={5}
      maxRadius={10}
      onExpand={expand}
    />,
  );
  const button = await screen.findByText("Expand coupon search to 10 km");
  expect(expand).not.toHaveBeenCalled();
  fireEvent.click(button);
  expect(expand).toHaveBeenCalledTimes(1);
});
