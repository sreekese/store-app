import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { authorized, raw } from "../auth/client";
import Categories from "./Categories";
import MerchantOffers from "./MerchantOffers";
import OfferModeration from "./OfferModeration";
import OfferBrowser from "./OfferBrowser";
import OfferDetail from "./OfferDetail";
import type { Offer } from "./types";
vi.mock("../auth/client", () => ({ authorized: vi.fn(), raw: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: null }) }));
const privateApi = vi.mocked(authorized),
  publicApi = vi.mocked(raw);
const category = {
  id: "c1",
  name: "Food & Drink",
  description: "Dining",
  is_active: true,
  revision: 1,
};
const offer: Offer = {
  id: "o1",
  merchant_id: "m1",
  store_id: null,
  category_id: "c1",
  title: "Lunch offer",
  description: "Fresh lunch",
  image_url: "",
  discount_type: "PERCENTAGE",
  discount_value: "20.00",
  minimum_purchase: "100.00",
  maximum_discount: "80.00",
  currency: "INR",
  customer_type: "NEW_CUSTOMERS",
  terms_conditions: "Dine-in only. Excludes drinks.",
  starts_at: "2026-09-01T00:00:00Z",
  expires_at: "2027-01-01T00:00:00Z",
  status: "DRAFT",
  moderation_note: "",
  approved: false,
  admin_hold: false,
  revision: 1,
  updated_at: "2026-09-01T00:00:00Z",
};
const publicOffer = {
  ...offer,
  business_name: "Demo Café",
  category_name: "Food & Drink",
  store_name: "Central branch",
  matched_store_id: "s1",
  city: "Kochi",
  area: "Fort Kochi",
  latitude: 9.965,
  longitude: 76.242,
  distance_meters: 1250,
};
function setup(node: ReactNode, path = "/") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function merchantMocks(items: Offer[] = []) {
  publicApi.mockResolvedValue([category]);
  privateApi.mockImplementation(async (path, options) => {
    if (path === "/merchant/profile") return { id: "m1", status: "VERIFIED" };
    if (path === "/merchant/stores")
      return [{ id: "s1", name: "Central branch", status: "ACTIVE" }];
    if (path === "/merchant/offers/config") return { moderation_enabled: true };
    if (options?.method === "POST" || options?.method === "PUT") return offer;
    if (path.startsWith("/merchant/offers")) return items;
    throw new Error("Unexpected " + path);
  });
}
beforeEach(() => {
  vi.resetAllMocks();
});
it("creates an admin category and preserves active state", async () => {
  privateApi.mockImplementation(async (_path, options) =>
    options?.method === "POST" ? category : [],
  );
  setup(<Categories />);
  fireEvent.change(await screen.findByLabelText("Category name"), {
    target: { value: "Food & Drink" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save category" }));
  expect(await screen.findByText("Category saved.")).toBeInTheDocument();
  const call = privateApi.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    name: "Food & Drink",
    description: "",
    is_active: true,
  });
});
it("category deletion requires confirmation and explains in-use rejection", async () => {
  privateApi.mockImplementation(async (_path, options) => {
    if (options?.method === "DELETE")
      throw new Error(
        "This category is used by offers. Deactivate it instead.",
      );
    return [category];
  });
  setup(<Categories />);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Delete category: Food & Drink",
    }),
  );
  expect(
    privateApi.mock.calls.some(([, options]) => options?.method === "DELETE"),
  ).toBe(false);
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm category deletion" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Deactivate it instead",
  );
  expect(privateApi).toHaveBeenCalledWith("/admin/categories/c1?revision=1", {
    method: "DELETE",
    body: undefined,
  });
});
it("merchant draft payload excludes privileged state and converts local dates", async () => {
  merchantMocks();
  setup(<MerchantOffers />);
  fireEvent.change(await screen.findByLabelText("Offer title"), {
    target: { value: "Lunch offer" },
  });
  fireEvent.change(screen.getByLabelText("Offer description"), {
    target: { value: "Fresh lunch" },
  });
  fireEvent.change(screen.getByLabelText("Offer category"), {
    target: { value: "c1" },
  });
  fireEvent.change(screen.getByLabelText("Offer terms"), {
    target: { value: "Dine-in only" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save offer draft" }));
  expect(
    await screen.findByText("Offer draft saved. Submit it when ready."),
  ).toBeInTheDocument();
  const body = JSON.parse(
    privateApi.mock.calls.find(([, options]) => options?.method === "POST")![1]!
      .body as string,
  );
  expect(body.title).toBe("Lunch offer");
  expect(body.starts_at).toMatch(/Z$/);
  expect(body.store_id).toBeNull();
  for (const key of ["merchant_id", "status", "approved", "admin_hold"])
    expect(body).not.toHaveProperty(key);
});
it("discount type switches clear incompatible amounts and caps", async () => {
  merchantMocks();
  setup(<MerchantOffers />);
  fireEvent.change(await screen.findByLabelText("Discount type"), {
    target: { value: "BOGO" },
  });
  expect(
    screen.queryByLabelText("Discount percentage"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Maximum discount (₹, optional)"),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Offer title"), {
    target: { value: "Two for one" },
  });
  fireEvent.change(screen.getByLabelText("Offer description"), {
    target: { value: "Fresh lunch" },
  });
  fireEvent.change(screen.getByLabelText("Offer category"), {
    target: { value: "c1" },
  });
  fireEvent.change(screen.getByLabelText("Offer terms"), {
    target: { value: "Buy one lunch, get one of equal value free." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save offer draft" }));
  await screen.findByText("Offer draft saved. Submit it when ready.");
  const body = JSON.parse(
    privateApi.mock.calls.find(([, options]) => options?.method === "POST")![1]!
      .body as string,
  );
  expect(body.discount_value).toBe("0");
  expect(body.maximum_discount).toBeNull();
});
it("offer editing sends the reviewed revision and preserves errors", async () => {
  merchantMocks([offer]);
  const base = privateApi.getMockImplementation()!;
  privateApi.mockImplementation(async (path, options) => {
    if (options?.method === "PUT")
      throw new Error("This offer changed. Reload it before continuing.");
    return base(path, options);
  });
  setup(<MerchantOffers />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit offer: Lunch offer" }),
  );
  fireEvent.change(screen.getByLabelText("Offer title"), {
    target: { value: "Updated lunch" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save offer draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This offer changed",
  );
  expect(screen.getByLabelText("Offer title")).toHaveValue("Updated lunch");
  const body = JSON.parse(
    privateApi.mock.calls.find(([, options]) => options?.method === "PUT")![1]!
      .body as string,
  );
  expect(body.revision).toBe(1);
});
it("cancelling an offer edit does not report a save", async () => {
  merchantMocks([offer]);
  setup(<MerchantOffers />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit offer: Lunch offer" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel offer edit" }));
  expect(
    screen.queryByText("Offer draft saved. Submit it when ready."),
  ).not.toBeInTheDocument();
  expect(
    privateApi.mock.calls.some(([, options]) => options?.method === "PUT"),
  ).toBe(false);
});
it("merchant submit and pause actions carry revisions", async () => {
  merchantMocks([offer]);
  setup(<MerchantOffers />);
  fireEvent.click(await screen.findByRole("button", { name: "Submit offer" }));
  await waitFor(() =>
    expect(privateApi).toHaveBeenCalledWith("/merchant/offers/o1/actions", {
      method: "POST",
      body: JSON.stringify({ action: "SUBMIT", revision: 1 }),
    }),
  );
});
it("unverified merchants cannot open an offer form", async () => {
  merchantMocks();
  const base = privateApi.getMockImplementation()!;
  privateApi.mockImplementation(async (path, options) =>
    path === "/merchant/profile"
      ? { id: "m1", status: "PENDING" }
      : base(path, options),
  );
  setup(<MerchantOffers />);
  expect(
    await screen.findByText(
      "Your business must be verified to create or edit offers.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Offer title")).not.toBeInTheDocument();
});
it("offer rejection requires a reason and sends the current revision", async () => {
  privateApi.mockResolvedValue([
    { ...offer, ...publicOffer, status: "PENDING_APPROVAL" },
  ]);
  setup(<OfferModeration />);
  const reject = await screen.findByRole("button", { name: "Reject offer" });
  expect(reject).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Review note for Lunch offer"), {
    target: { value: "Clarify exclusions" },
  });
  fireEvent.click(reject);
  await waitFor(() =>
    expect(privateApi).toHaveBeenCalledWith("/admin/offers/o1/review", {
      method: "POST",
      body: JSON.stringify({
        action: "REJECT",
        note: "Clarify exclusions",
        revision: 1,
      }),
    }),
  );
});
it("admin suspension is explicit and requires a reason", async () => {
  privateApi.mockResolvedValue([
    { ...offer, ...publicOffer, status: "ACTIVE", approved: true },
  ]);
  setup(<OfferModeration />);
  const suspend = await screen.findByRole("button", { name: "Suspend offer" });
  expect(suspend).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Review note for Lunch offer"), {
    target: { value: "Policy issue" },
  });
  fireEvent.click(suspend);
  await waitFor(() =>
    expect(privateApi).toHaveBeenCalledWith("/admin/offers/o1/review", {
      method: "POST",
      body: JSON.stringify({
        action: "SUSPEND",
        note: "Policy issue",
        revision: 1,
      }),
    }),
  );
});
function browseMock(offers = [publicOffer]) {
  publicApi.mockImplementation(async (path) =>
    path === "/categories"
      ? [category]
      : { offers, next_offset: null, radius_km: 5 },
  );
}
it("nearby offer browsing sends the selected centre, radius, and category", async () => {
  browseMock();
  setup(
    <OfferBrowser
      centre={{ latitude: 9.965, longitude: 76.242, label: "Fort Kochi" }}
      radius={5}
    />,
  );
  expect(await screen.findByText("Lunch offer")).toBeInTheDocument();
  expect(screen.getByText("1.25 km away")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Food & Drink" }));
  await waitFor(() =>
    expect(
      publicApi.mock.calls.some(
        ([path]) =>
          path.includes("latitude=9.965") &&
          path.includes("radius_km=5") &&
          path.includes("category_id=c1"),
      ),
    ).toBe(true),
  );
  expect(
    await screen.findByRole("link", { name: "View offer details" }),
  ).toHaveAttribute("href", "/offers/o1?store_id=s1");
});
it("category and offer empty states are useful", async () => {
  browseMock([]);
  setup(<OfferBrowser centre={null} radius={null} />);
  expect(
    await screen.findByText("No matching offers right now."),
  ).toBeInTheDocument();
  expect(screen.getByText(/Browsing all listed locations/)).toBeInTheDocument();
});
it("failed offer browsing offers retry without a false empty state", async () => {
  publicApi.mockImplementation(async (path) => {
    if (path === "/categories") return [category];
    throw new Error("Offers unavailable");
  });
  setup(<OfferBrowser centre={null} radius={null} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Offers unavailable",
  );
  expect(
    screen.queryByText("No matching offers right now."),
  ).not.toBeInTheDocument();
  browseMock();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Lunch offer")).toBeInTheDocument();
});
it("public offer details show complete terms without claiming a coupon", async () => {
  publicApi.mockImplementation(async (path) =>
    path.includes("/campaigns?")
      ? []
      : path.startsWith("/trust/reviews")
        ? { items: [], count: 0, average: null, next_offset: null }
        : publicOffer,
  );
  setup(
    <Routes>
      <Route path="/offers/:id" element={<OfferDetail />} />
    </Routes>,
    "/offers/o1?store_id=s1",
  );
  expect(
    await screen.findByRole("heading", { name: "Lunch offer" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Dine-in only. Excludes drinks."),
  ).toBeInTheDocument();
  expect(
    await screen.findByText(/does not reserve a coupon/),
  ).toBeInTheDocument();
  expect(screen.getByText("NEW CUSTOMERS")).toBeInTheDocument();
  expect(publicApi).toHaveBeenCalledWith("/offers/o1?store_id=s1");
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
    "href",
    "/login?returnTo=%2Foffers%2Fo1%3Fstore_id%3Ds1",
  );
});
it("expired offer detail returns an unavailable state", async () => {
  publicApi.mockRejectedValue(
    new Error("This offer is unavailable, paused, or expired."),
  );
  setup(
    <Routes>
      <Route path="/offers/:id" element={<OfferDetail />} />
    </Routes>,
    "/offers/o1",
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("expired");
  expect(
    screen.queryByRole("heading", { name: "Lunch offer" }),
  ).not.toBeInTheDocument();
});
