import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import StaffManager from "./StaffManager";
import type { Merchant, Store } from "./shared";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
const api = vi.mocked(authorized);
const profile = { id: "m1", status: "VERIFIED" } as Merchant;
const store = {
  id: "s1",
  name: "Central",
  city: "Kochi",
  status: "ACTIVE",
} as Store;
const member = {
  id: "u1",
  display_name: "Team member",
  email: "staff@example.com",
  store_ids: ["s1"],
  revision: 4,
  account_active: true,
};
const invitation = {
  id: "i1",
  email: "invited@example.com",
  store_ids: ["s1"],
  status: "PENDING",
  expires_at: "2020-01-01T00:00:00Z",
  closed_at: null,
  accepted_at: null,
};
function setup(status = "VERIFIED") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <StaffManager profile={{ ...profile, status }} />
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.mockImplementation(async (path, options) => {
    if (path === "/merchant/stores") return [store];
    if (path === "/merchant/staff") return [member];
    if (path === "/merchant/invitations") return [invitation];
    if (path.includes("/assignments")) return undefined;
    if (path.endsWith("/reissue")) return { token: "new-private-token" };
    if (path.includes("staff-audit")) return [];
    if (options?.method === "DELETE") return undefined;
    return [];
  });
});
it("sends the current staff revision when revoking business access", async () => {
  setup();
  fireEvent.click(await screen.findByText("Revoke all access"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/staff/u1/assignments", {
      method: "PUT",
      body: JSON.stringify({ revision: 4, store_ids: [] }),
    }),
  );
  expect(
    screen.getByText(/assignments at other businesses/),
  ).toBeInTheDocument();
});
it("keeps revoked people visible and restores only selected branches", async () => {
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) =>
    p === "/merchant/staff"
      ? [{ ...member, store_ids: [], revision: 5 }]
      : base(p, o),
  );
  setup();
  await screen.findByText("Access revoked for this business");
  const card = screen
    .getByRole("heading", { name: "Team member" })
    .closest("article")!;
  expect(within(card).getByText("Restore selected access")).toBeDisabled();
  fireEvent.click(within(card).getByRole("checkbox"));
  fireEvent.click(within(card).getByText("Restore selected access"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/staff/u1/assignments", {
      method: "PUT",
      body: JSON.stringify({ revision: 5, store_ids: ["s1"] }),
    }),
  );
});
it("blocks regrants for unavailable accounts but allows revocation", async () => {
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) =>
    p === "/merchant/staff"
      ? [{ ...member, account_active: false }]
      : base(p, o),
  );
  setup();
  await screen.findByText("Account unavailable");
  expect(screen.getByText("Save assignments")).toBeDisabled();
  expect(screen.getByText("Revoke all access")).not.toBeDisabled();
});
it("allows revocation but disables invitations and restoration during suspension", async () => {
  setup("SUSPENDED");
  await screen.findByText("Revoke all access");
  expect(screen.getByText("Revoke all access")).not.toBeDisabled();
  expect(screen.getByText("Save assignments")).toBeDisabled();
  expect(screen.getByText("Reissue invitation")).toBeDisabled();
  expect(screen.getByText("Create invitation link")).toBeDisabled();
});
it("reissues a link privately and clears it when cancelled", async () => {
  setup();
  await screen.findByText(/PENDING · Expires/);
  fireEvent.click(screen.getByText("Reissue invitation"));
  const input = await screen.findByLabelText("Share this invitation link");
  expect(input).toHaveValue(
    `${window.location.origin}/staff/accept-invitation#token=new-private-token`,
  );
  expect(api).toHaveBeenCalledWith("/merchant/invitations/i1/reissue", {
    method: "POST",
    body: undefined,
  });
  fireEvent.click(screen.getByText("Cancel invitation"));
  await waitFor(() =>
    expect(
      screen.queryByLabelText("Share this invitation link"),
    ).not.toBeInTheDocument(),
  );
});
it("filters and paginates invitations and does not reissue accepted links", async () => {
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) =>
    p === "/merchant/invitations"
      ? Array.from({ length: 25 }, (_, n) => ({
          ...invitation,
          id: `i${n}`,
          email: `person${n}@example.com`,
          status: "ACCEPTED",
        }))
      : base(p, o),
  );
  setup();
  await screen.findByText("person24@example.com");
  expect(screen.queryByText("Reissue invitation")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("More invitations"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/invitations?offset=25"),
  );
  fireEvent.change(screen.getByLabelText("Invitation status"), {
    target: { value: "EXPIRED" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/invitations?status=EXPIRED"),
  );
});
it("hides cached staff details on a failed refresh", async () => {
  setup();
  await screen.findByText("Team member");
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) => {
    if (p === "/merchant/staff") throw Error("Session unavailable");
    return base(p, o);
  });
  fireEvent.click(screen.getByText("Refresh staff access"));
  await screen.findByText("Session unavailable");
  expect(screen.queryByText("staff@example.com")).not.toBeInTheDocument();
});
it("shows stale-edit failures and lets the owner refresh the roster", async () => {
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) => {
    if (p.includes("/assignments"))
      throw Error("Staff access changed. Refresh the roster before saving.");
    return base(p, o);
  });
  setup();
  fireEvent.click(await screen.findByText("Revoke all access"));
  expect(await screen.findByText(/Staff access changed/)).toBeInTheDocument();
  expect(screen.getByText("Refresh staff access")).not.toBeDisabled();
});
it("loads merchant audit history on demand with before and after branches", async () => {
  const base = api.getMockImplementation()!;
  api.mockImplementation(async (p, o) =>
    p.includes("staff-audit")
      ? [
          {
            id: "a1",
            action: "STAFF_ASSIGNMENTS_CHANGED",
            actor: "Owner",
            subject: "Team member",
            before_stores: ["Central"],
            stores: [],
            created_at: "2026-10-04T10:00:00Z",
          },
        ]
      : base(p, o),
  );
  setup();
  await screen.findByText("Team member");
  expect(api.mock.calls.some((c) => c[0].includes("staff-audit"))).toBe(false);
  const details = screen
    .getByText("View staff access history")
    .closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(await screen.findByText("Central → No branches")).toBeInTheDocument();
  expect(screen.getByText("Team member · by Owner")).toBeInTheDocument();
});
it("keeps stale invitation controls disabled until the rotated list arrives", async () => {
  const base = api.getMockImplementation()!;
  let reads = 0;
  let release!: (value: unknown) => void;
  api.mockImplementation(async (path, options) => {
    if (path === "/merchant/invitations") {
      reads++;
      if (reads === 1) return [invitation];
      if (reads === 2)
        return new Promise((resolve) => {
          release = resolve;
        });
      return [{ ...invitation, id: "i2" }];
    }
    return base(path, options);
  });
  setup();
  fireEvent.click(await screen.findByText("Reissue invitation"));
  await waitFor(() => expect(reads).toBe(2));
  expect(screen.getByText("Cancel invitation")).toBeDisabled();
  expect(screen.getByText("Reissue invitation")).toBeDisabled();
  release([{ ...invitation, id: "i2" }]);
  await waitFor(() =>
    expect(screen.getByText("Cancel invitation")).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("Cancel invitation"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/merchant/invitations/i2", {
      method: "DELETE",
      body: undefined,
    }),
  );
});
