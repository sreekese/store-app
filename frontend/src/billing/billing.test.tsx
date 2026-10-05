import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import Billing from "./Billing";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "u1" } }),
}));
const api = vi.mocked(authorized);
const plan = {
  id: "p1",
  revision: 2,
  name: "Test plan",
  description: "Test subscription",
  currency: "INR",
  amount_minor: 12000,
  period_days: 30,
  is_active: true,
};
const payment = {
  id: "pay1",
  merchant_name: "Test business",
  plan_name: "Test plan",
  currency: "INR",
  amount_minor: 12000,
  period_days: 30,
  status: "PENDING",
  created_at: "2026-10-01T00:00:00Z",
  paid_at: null,
  starts_at: null,
  expires_at: null,
  provider: "sandbox",
};
let paid = false,
  enabled = true,
  failPayments = false;
beforeEach(() => {
  vi.resetAllMocks();
  paid = false;
  enabled = true;
  failPayments = false;
  api.mockImplementation(async (path, options) => {
    if (path === "/billing/config")
      return { enabled, provider: enabled ? "sandbox" : "disabled" };
    if (path === "/billing/subscription")
      return { status: "INACTIVE", payment: null };
    if (path.startsWith("/billing/plans?"))
      return { items: [plan], next_offset: null };
    if (path.startsWith("/billing/payments?")) {
      if (failPayments) throw new Error("Billing unavailable");
      return {
        items: [
          {
            ...payment,
            ...(paid
              ? { status: "PAID", paid_at: "2026-10-01T00:00:00Z" }
              : {}),
          },
        ],
        next_offset: null,
      };
    }
    if (path.endsWith("/invoice"))
      return {
        number: "SANDBOX-TEST",
        issued_at: "2026-10-01T00:00:00Z",
        kind: "SANDBOX_INVOICE",
        payment: { ...payment, status: "PAID" },
      };
    if (path.endsWith("/refund")) return { status: "REQUESTED" };
    if (path === "/billing/orders") return payment;
    if (options?.method === "PUT" || options?.method === "POST") return plan;
    throw new Error("Unexpected endpoint");
  });
});
function setup(superadmin = false) {
  return render(
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
        <Billing superadmin={superadmin} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
it("reviews price and submits current plan revision without granting success", async () => {
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "Review Test plan" }),
  );
  expect(
    screen.getByText("Test plan · INR 120.00 · 30 days"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Create sandbox order" }));
  await screen.findByText("Order saved. Awaiting payment confirmation.");
  const call = api.mock.calls.find(([path]) => path === "/billing/orders");
  expect(JSON.parse(call![1]!.body as string)).toEqual({
    plan_id: "p1",
    plan_revision: 2,
    request_key: expect.any(String),
  });
  expect(screen.getByText("INACTIVE")).toBeInTheDocument();
});
it("retries an interrupted checkout with the same idempotency key", async () => {
  const original = api.getMockImplementation()!;
  let tries = 0;
  api.mockImplementation(async (path, options) => {
    if (path === "/billing/orders" && tries++ === 0)
      throw new Error("Connection lost");
    return original(path, options);
  });
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "Review Test plan" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create sandbox order" }));
  await screen.findByText("Connection lost");
  fireEvent.click(screen.getByRole("button", { name: "Create sandbox order" }));
  await screen.findByText("Order saved. Awaiting payment confirmation.");
  const calls = api.mock.calls.filter(([p]) => p === "/billing/orders");
  expect(calls[0][1]!.body).toBe(calls[1][1]!.body);
});
it("disabled billing prevents checkout", async () => {
  enabled = false;
  setup();
  expect(
    await screen.findByRole("button", { name: "Review Test plan" }),
  ).toBeDisabled();
  expect(screen.getByText("Checkout is not configured.")).toBeInTheDocument();
});
it("pending payments have no invoice or refund action", async () => {
  setup(true);
  await screen.findByText("Order pay1");
  expect(
    screen.queryByRole("button", { name: "View sandbox invoice" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Full refund reason")).not.toBeInTheDocument();
});
it("paid payments show a clearly labelled downloadable sandbox invoice", async () => {
  paid = true;
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "View sandbox invoice" }),
  );
  expect(
    await screen.findByText("Sandbox invoice — not a tax invoice"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Download sandbox invoice" }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Full refund reason")).not.toBeInTheDocument();
});
it("superadmin refund waits for webhook confirmation", async () => {
  paid = true;
  setup(true);
  fireEvent.change(await screen.findByLabelText("Full refund reason"), {
    target: { value: "Requested sandbox refund" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Request full sandbox refund" }),
  );
  expect(
    await screen.findByText("Refund requested; awaiting confirmation."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Test business · INR 120.00 · PAID · Sandbox"),
  ).toBeInTheDocument();
});
it("plan edits include revision and integer minor units", async () => {
  setup(true);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit Test plan" }),
  );
  fireEvent.change(
    screen.getByLabelText("Price in minor units (100 = 1 currency unit)"),
    { target: { value: "25000" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Save plan" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/billing/plans/p1", {
      method: "PUT",
      body: JSON.stringify({
        name: plan.name,
        description: plan.description,
        currency: "INR",
        amount_minor: 25000,
        period_days: 30,
        is_active: true,
        revision: 2,
      }),
    }),
  );
});
it("failed refresh hides cached payment history", async () => {
  setup();
  await screen.findByText("Order pay1");
  failPayments = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh payments" }));
  await screen.findByText("Billing unavailable");
  expect(screen.queryByText("Order pay1")).not.toBeInTheDocument();
});
