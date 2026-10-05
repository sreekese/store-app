import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { authorized, raw } from "../auth/client";
import ShopperProfile from "./ShopperProfile";
import MerchantWorkspace from "./MerchantWorkspace";
import AdminReviews from "./AdminReviews";
import StaffStores from "./StaffStores";
import AcceptInvitation from "./AcceptInvitation";
vi.mock("../auth/client", () => ({ authorized: vi.fn(), raw: vi.fn() }));
const api = vi.mocked(authorized),
  publicApi = vi.mocked(raw);
const merchant = {
  id: "m1",
  business_name: "Local Café",
  category: "Café",
  description: "Fresh food",
  contact_email: "cafe@example.com",
  phone: "9876543210",
  status: "VERIFIED",
  review_note: "",
  revision: 2,
  updated_at: "2026-09-27T10:00:00Z",
};
const store = {
  id: "s1",
  merchant_id: "m1",
  name: "Central branch",
  city: "Kochi",
  address: "Market Road",
};
const profile = {
  email: "shopper@example.com",
  display_name: "Neha",
  phone: "",
  city: "Kochi",
  area: "",
  postal_code: "",
  location_preference: "MANUAL",
};
function setup(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
function merchantApi(status = "VERIFIED") {
  api.mockImplementation(async (path, options) => {
    if (path === "/merchant/profile") return { ...merchant, status };
    if (path === "/merchant/stores") return [store];
    if (path === "/merchant/staff") return [];
    if (path === "/merchant/invitations" && options?.method === "POST")
      return { token: "one-time-token" };
    if (path === "/merchant/invitations") return [];
    throw new Error("Unexpected " + path);
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState(null, "", "/");
});
afterEach(() => window.history.replaceState(null, "", "/"));
it("loads shopper profile and saves only editable fields", async () => {
  api
    .mockResolvedValueOnce(profile)
    .mockResolvedValueOnce({ ...profile, display_name: "New name" });
  setup(<ShopperProfile />);
  fireEvent.change(await screen.findByLabelText("Display name"), {
    target: { value: "New name" },
  });
  expect(screen.getByLabelText("Account email")).toHaveAttribute("readonly");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByText("Profile saved.")).toBeInTheDocument();
  const options = api.mock.calls[1][1]!;
  expect(options.method).toBe("PUT");
  expect(JSON.parse(options.body as string)).toEqual({
    ...profile,
    email: undefined,
    display_name: "New name",
  });
});
it("shows profile save errors without losing entered text", async () => {
  api
    .mockResolvedValueOnce(profile)
    .mockRejectedValueOnce(new Error("Could not save profile"));
  setup(<ShopperProfile />);
  fireEvent.change(await screen.findByLabelText("City"), {
    target: { value: "Thrissur" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not save profile",
  );
  expect(screen.getByLabelText("City")).toHaveValue("Thrissur");
});
it("can retry a failed profile load", async () => {
  api
    .mockRejectedValueOnce(new Error("Service unavailable"))
    .mockResolvedValueOnce(profile);
  setup(<ShopperProfile />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Service unavailable",
  );
  fireEvent.click(screen.getByText("Try again"));
  expect(await screen.findByLabelText("Display name")).toHaveValue("Neha");
});
it("submits a new business without owner or verification fields", async () => {
  api.mockResolvedValue(null);
  setup(<MerchantWorkspace />);
  fireEvent.change(await screen.findByLabelText("Business name"), {
    target: { value: "Local Café" },
  });
  fireEvent.change(screen.getByLabelText("Business category"), {
    target: { value: "Café" },
  });
  fireEvent.change(screen.getByLabelText("Business contact email"), {
    target: { value: "cafe@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Business phone"), {
    target: { value: "9876543210" },
  });
  merchantApi("PENDING");
  fireEvent.click(
    screen.getByRole("button", { name: "Submit for verification" }),
  );
  expect(
    await screen.findByText("Business submitted for review."),
  ).toBeInTheDocument();
  const call = api.mock.calls.find(([, options]) => options?.method === "PUT")!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    business_name: "Local Café",
    category: "Café",
    contact_email: "cafe@example.com",
    phone: "9876543210",
    description: "",
    website: "",
    logo_url: "",
    cover_image_url: "",
  });
});
it("keeps staff invitations disabled until merchant verification", async () => {
  merchantApi("PENDING");
  setup(<MerchantWorkspace />);
  expect(
    await screen.findByRole("button", { name: "Create invitation link" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Staff email")).toBeDisabled();
});
it("requires a selected branch and returns a privately shareable invitation", async () => {
  merchantApi();
  setup(<MerchantWorkspace />);
  const button = await screen.findByRole("button", {
    name: "Create invitation link",
  });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Staff email"), {
    target: { value: "staff@example.com" },
  });
  fireEvent.click(await screen.findByLabelText("Central branch · Kochi"));
  fireEvent.click(button);
  const link = await screen.findByLabelText("Share this invitation link");
  expect(link).toHaveValue(
    window.location.origin + "/staff/accept-invitation#token=one-time-token",
  );
  const call = api.mock.calls.find(
    ([, options]) => options?.method === "POST",
  )!;
  expect(JSON.parse(call[1]!.body as string)).toEqual({
    email: "staff@example.com",
    store_ids: ["s1"],
  });
});
it("revokes all store assignments through the merchant control", async () => {
  merchantApi();
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (path, options) => {
    if (path === "/merchant/staff")
      return [
        {
          id: "u1",
          revision: 1,
          account_active: true,
          email: "staff@example.com",
          display_name: "Staff One",
          store_ids: ["s1"],
        },
      ];
    if (path.includes("/assignments")) return undefined;
    return base(path, options);
  });
  setup(<MerchantWorkspace />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Revoke all access" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/staff/u1/assignments", {
      method: "PUT",
      body: JSON.stringify({ revision: 1, store_ids: [] }),
    }),
  );
});
it("admin rejection requires a reason and submits the reviewed revision", async () => {
  api.mockResolvedValue([{ ...merchant, status: "PENDING", revision: 1 }]);
  setup(<AdminReviews />);
  const reject = await screen.findByRole("button", { name: "Reject business" });
  expect(reject).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Review note for Local Café"), {
    target: { value: "Please correct contact details" },
  });
  fireEvent.click(reject);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/admin/merchants/m1/review", {
      method: "PUT",
      body: JSON.stringify({
        status: "REJECTED",
        note: "Please correct contact details",
        revision: 1,
      }),
    }),
  );
});
it("admin can reload after a conflicting review", async () => {
  api.mockImplementation(async (_path, options) => {
    if (options?.method === "PUT")
      throw new Error("This profile changed. Reload it before reviewing.");
    return [{ ...merchant, status: "PENDING", revision: 1 }];
  });
  setup(<AdminReviews />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Approve business" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This profile changed",
  );
  fireEvent.click(screen.getByRole("button", { name: "Reload queue" }));
  await waitFor(() =>
    expect(
      api.mock.calls.filter(([path]) => path.includes("?offset=")).length,
    ).toBe(2),
  );
});
it("staff sees an empty assignment state", async () => {
  api.mockResolvedValue([]);
  setup(<StaffStores />);
  expect(
    await screen.findByText(/No active store assignments/),
  ).toBeInTheDocument();
});
it("staff opening a removed store shows the server denial", async () => {
  api
    .mockResolvedValueOnce([store])
    .mockRejectedValueOnce(new Error("You do not have access to this store."))
    .mockResolvedValue([]);
  setup(<StaffStores />);
  fireEvent.click(await screen.findByRole("button", { name: "Open store" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "You do not have access",
  );
  expect(
    await screen.findByText(/No active store assignments/),
  ).toBeInTheDocument();
});
it("invitation acceptance keeps tokens in request bodies and directs staff to login", async () => {
  window.history.replaceState(
    null,
    "",
    "/staff/accept-invitation#token=private-token",
  );
  publicApi
    .mockResolvedValueOnce({
      email: "staff@example.com",
      business_name: "Local Café",
      stores: ["Central branch"],
      expires_at: "2026-10-04T10:00:00Z",
    })
    .mockResolvedValueOnce({});
  setup(<AcceptInvitation />);
  fireEvent.change(await screen.findByLabelText("Your name"), {
    target: { value: "Neha" },
  });
  fireEvent.change(screen.getByLabelText("Staff password"), {
    target: { value: "A-long-staff-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
  expect(
    await screen.findByRole("heading", { name: "You’re on the team." }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Continue to staff sign in" }),
  ).toHaveAttribute("href", "/staff/login");
  expect(window.location.hash).toBe("");
  expect(
    publicApi.mock.calls.every(([path]) => !path.includes("private-token")),
  ).toBe(true);
});
it("invalid invitation links show a useful error without an acceptance form", async () => {
  window.history.replaceState(
    null,
    "",
    "/staff/accept-invitation#token=expired-token",
  );
  publicApi.mockRejectedValue(
    new Error("This invitation is invalid, expired, or already used."),
  );
  setup(<AcceptInvitation />);
  expect(await screen.findByRole("alert")).toHaveTextContent("expired");
  expect(
    screen.queryByRole("button", { name: "Accept invitation" }),
  ).not.toBeInTheDocument();
});
it("missing invitation tokens do not make a request", () => {
  setup(<AcceptInvitation />);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "missing its invitation token",
  );
  expect(publicApi).not.toHaveBeenCalled();
});
it("admin empty queue and filters remain usable", async () => {
  api.mockResolvedValue([]);
  setup(<AdminReviews />);
  expect(
    await screen.findByText("No businesses in this queue."),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Verification status"), {
    target: { value: "SUSPENDED" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/admin/merchants?offset=0&status=SUSPENDED",
    ),
  );
  expect(
    within(screen.getByLabelText("Verification status")).getByRole("option", {
      name: "SUSPENDED",
    }),
  ).toBeInTheDocument();
});
