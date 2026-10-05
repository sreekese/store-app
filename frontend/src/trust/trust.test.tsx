import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { authorized, raw } from "../auth/client";
import type { Role } from "../auth/types";
import Support, { ReportForm } from "./Support";
import Reviews, { ReviewForm, ReviewModeration } from "./Reviews";
vi.mock("../auth/client", () => ({ authorized: vi.fn(), raw: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "u1", role: "USER" } }),
}));
const api = vi.mocked(authorized),
  publicApi = vi.mocked(raw);
const item = {
  id: "case1",
  reference: "NP-case1",
  title: "Lunch offer",
  store_name: "Central",
  reason: "INCORRECT_DISCOUNT",
  status: "OPEN",
  revision: 1,
  description: "The discount was not applied.",
  resolution: "",
  claim_id: "c1",
  redemption_id: null,
  context: {
    offer: {
      terms_conditions: "Original saved terms",
      minimum_purchase: "100",
    },
    expires_at: "2026-09-29T10:00:00Z",
    status_at_report: "CLAIMED",
  },
};
const review = {
  id: "r1",
  rating: 4,
  comment: "Very helpful staff",
  status: "PENDING",
  revision: 1,
  moderation_reason: "",
  store_id: "s1",
  created_at: "2026-09-29T10:00:00Z",
};
function setup(element: ReactNode, path = "/app/support", role: Role = "USER") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        {element || (
          <Routes>
            <Route
              path="/:workspace/support"
              element={<Support role={role} />}
            />
            <Route
              path="/:workspace/support/:id"
              element={<Support role={role} />}
            />
          </Routes>
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.mockImplementation(async (path) =>
    path.includes("/history")
      ? {
          items: [
            {
              id: "a1",
              actor_role: "USER",
              kind: "CREATED",
              message: "Case opened.",
              status: "OPEN",
              created_at: "2026-09-29T10:00:00Z",
            },
          ],
          next_offset: null,
        }
      : path.includes("/cases/case1")
        ? item
        : path.includes("moderation")
          ? { items: [], next_offset: null }
          : { items: [item], next_offset: null },
  );
});
it("submits a review with the owned redemption and shows moderation status", async () => {
  api.mockResolvedValue({ review: null });
  setup(<ReviewForm redemptionId="redeemed1" />);
  fireEvent.change(await screen.findByLabelText("Your experience"), {
    target: { value: "Helpful service" },
  });
  fireEvent.change(screen.getByLabelText("Rating"), { target: { value: "3" } });
  fireEvent.click(screen.getByText("Submit review"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/trust/reviews", {
      method: "POST",
      body: JSON.stringify({
        redemption_id: "redeemed1",
        rating: 3,
        comment: "Helpful service",
      }),
    }),
  );
});
it("shows an existing hidden review and prevents a second form", async () => {
  api.mockResolvedValue({
    review: {
      ...review,
      status: "HIDDEN",
      moderation_reason: "Remove personal details",
    },
  });
  setup(<ReviewForm redemptionId="r1" />);
  expect(await screen.findByText("4/5 · HIDDEN")).toBeInTheDocument();
  expect(screen.queryByText("Submit review")).not.toBeInTheDocument();
  expect(screen.getByText(/Remove personal details/)).toBeInTheDocument();
});
it("creates a coupon refusal case and links to its reference", async () => {
  api.mockResolvedValue(item);
  setup(
    <ReportForm
      target="CLAIM"
      id="c1"
      stores={[{ id: "s1", name: "Central" }]}
    />,
  );
  fireEvent.change(screen.getByLabelText("What happened?"), {
    target: { value: "The store refused my coupon." },
  });
  fireEvent.click(screen.getByText("Submit report"));
  expect(await screen.findByRole("link", { name: "NP-case1" })).toHaveAttribute(
    "href",
    "/app/support/case1",
  );
  expect(api).toHaveBeenCalledWith("/trust/cases", {
    method: "POST",
    body: JSON.stringify({
      target_type: "CLAIM",
      target_id: "c1",
      store_id: "s1",
      reason: "STORE_REFUSED_COUPON",
      description: "The store refused my coupon.",
    }),
  });
});
it("shows errors without losing the report draft", async () => {
  api.mockRejectedValue(Error("Already reported. Follow your existing case."));
  setup(
    <ReportForm
      target="OFFER"
      id="o1"
      stores={[{ id: "s1", name: "Central" }]}
    />,
  );
  expect(
    screen.queryByRole("option", { name: "STORE REFUSED COUPON" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("What happened?"), {
    target: { value: "The listing is incorrect." },
  });
  fireEvent.click(screen.getByText("Submit report"));
  expect(await screen.findByText(/Already reported/)).toBeInTheDocument();
  expect(screen.getByLabelText("What happened?")).toHaveValue(
    "The listing is incorrect.",
  );
});
it("filters the scoped case queue and hides moderation from shoppers", async () => {
  setup(null);
  expect(
    await screen.findByRole("link", { name: "Lunch offer" }),
  ).toHaveAttribute("href", "/app/support/case1");
  expect(screen.queryByText("Review moderation")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Case status"), {
    target: { value: "OPEN" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/trust/cases?offset=0&status=OPEN"),
  );
});
it("shows saved terms and response history but no staff resolution control", async () => {
  setup(null, "/staff/support/case1", "MERCHANT_STAFF");
  expect(await screen.findByText("Original saved terms")).toBeInTheDocument();
  expect(await screen.findByText("Case opened.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Case action")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Response"), {
    target: { value: "Checking with the store." },
  });
  fireEvent.click(screen.getByText("Send response"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/trust/cases/case1/respond", {
      method: "POST",
      body: JSON.stringify({
        revision: 1,
        message: "Checking with the store.",
      }),
    }),
  );
});
it("admin resolution includes the current revision and required explanation", async () => {
  api.mockImplementation(async (path) =>
    path.includes("history")
      ? { items: [], next_offset: null }
      : { ...item, status: "UNDER_REVIEW", revision: 3 },
  );
  setup(null, "/admin/support/case1", "ADMIN");
  fireEvent.change(await screen.findByLabelText("Case action"), {
    target: { value: "RESOLVED" },
  });
  expect(screen.getByText("Resolve case")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Resolution"), {
    target: { value: "Receipt verified with both parties." },
  });
  fireEvent.click(screen.getByText("Resolve case"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/trust/cases/case1/transition", {
      method: "POST",
      body: JSON.stringify({
        revision: 3,
        message: "Receipt verified with both parties.",
        status: "RESOLVED",
      }),
    }),
  );
});
it("resolved cases show the decision and hide response forms", async () => {
  api.mockImplementation(async (path) =>
    path.includes("history")
      ? { items: [], next_offset: null }
      : {
          ...item,
          status: "RESOLVED",
          resolution: "Agreed with the store",
          resolved_at: "2026-09-29T10:00:00Z",
        },
  );
  setup(null, "/app/support/case1");
  expect(await screen.findByText("Agreed with the store")).toBeInTheDocument();
  expect(screen.queryByText("Send response")).not.toBeInTheDocument();
});
it("hides cached private case details after a failed refresh", async () => {
  setup(null, "/app/support/case1");
  await screen.findByText("Original saved terms");
  api.mockRejectedValue(Error("Session unavailable"));
  fireEvent.click(screen.getByText("Refresh case"));
  await screen.findByText("Session unavailable");
  expect(screen.queryByText("Original saved terms")).not.toBeInTheDocument();
});
it("renders published ratings, safely escapes content and switches branch scope", async () => {
  publicApi.mockResolvedValue({
    items: [{ ...review, comment: "<script>alert(1)</script>" }],
    count: 1,
    average: 4,
    next_offset: null,
  });
  setup(<Reviews offerId="o1" storeId="s1" />);
  expect(await screen.findByText("4/5 from 1 reviews")).toBeInTheDocument();
  expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  fireEvent.change(screen.getByLabelText("Reviews for"), {
    target: { value: "store" },
  });
  await waitFor(() =>
    expect(publicApi).toHaveBeenCalledWith(
      "/trust/reviews?store_id=s1&offset=0",
    ),
  );
});
it("moderation requires a reason and sends the versioned decision", async () => {
  api.mockResolvedValue({ items: [review], next_offset: null });
  setup(<ReviewModeration />);
  fireEvent.change(await screen.findByLabelText("Moderation reason"), {
    target: { value: "Meets community guidelines." },
  });
  fireEvent.click(screen.getByText("Save moderation decision"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/trust/reviews/r1/moderate", {
      method: "POST",
      body: JSON.stringify({
        revision: 1,
        status: "PUBLISHED",
        reason: "Meets community guidelines.",
      }),
    }),
  );
});
