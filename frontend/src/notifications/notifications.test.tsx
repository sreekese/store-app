import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import type { Role } from "../auth/types";
import Inbox from "./Inbox";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "u1", role: "USER" } }),
}));
const api = vi.mocked(authorized);
const preferences = {
  email_enabled: false,
  daily_enabled: true,
  email_mode: "LOCAL_CAPTURE",
};
const note = {
  id: "n1",
  title: "Coupon claim recorded",
  body: "Open your wallet for current status.",
  link: "/app/coupons/c1",
  created_at: "2026-09-29T09:00:00Z",
  read_at: null,
  stale: false,
};
const page = { items: [note], unread_count: 1, next_offset: null };
function setup(role: Role = "USER") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <Inbox role={role} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return client;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.mockImplementation(async (path) =>
    path === "/notifications/preferences"
      ? preferences
      : path.startsWith("/notifications/operations")
        ? []
        : page,
  );
});
it("shows private updates and an owned wallet link", async () => {
  setup();
  expect(await screen.findByText("Coupon claim recorded")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open details" })).toHaveAttribute(
    "href",
    "/app/coupons/c1",
  );
  expect(screen.getByText("1 unread")).toBeInTheDocument();
  expect(
    screen.queryByText("Failed notification jobs"),
  ).not.toBeInTheDocument();
});
it("marks one update or all updates read and filters unread", async () => {
  setup();
  fireEvent.click(await screen.findByText("Mark as read"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/notifications/n1/read", {
      method: "POST",
    }),
  );
  fireEvent.click(screen.getByLabelText("Unread only"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/notifications?unread=true&offset=0"),
  );
  await waitFor(() =>
    expect(screen.getByText("Mark all as read")).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByText("Mark all as read"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/notifications/read-all", {
      method: "POST",
    }),
  );
});
it("discloses local-only email and saves preferences without server-owned fields", async () => {
  setup();
  await screen.findByLabelText("Email notifications");
  expect(
    screen.getByText(/stored locally and are not sent/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Email notifications"));
  await waitFor(() =>
    expect(api.mock.calls.some((c) => c[1]?.method === "PUT")).toBe(true),
  );
  const body = api.mock.calls.find((c) => c[1]?.method === "PUT")![1]!.body;
  expect(JSON.parse(body as string)).toEqual({
    email_enabled: true,
    daily_enabled: true,
  });
});
it("hides stale cached messages after an inbox error and supports retry", async () => {
  const client = setup();
  await screen.findByText(note.title);
  api.mockImplementation(async (path) => {
    if (path === "/notifications/preferences") return preferences;
    throw Error("Session unavailable");
  });
  await client.invalidateQueries({ queryKey: ["notifications"] });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Session unavailable",
  );
  expect(screen.queryByText(note.title)).not.toBeInTheDocument();
});
it("shows empty and outdated states without following unsafe links", async () => {
  api.mockImplementation(async (path) =>
    path === "/notifications/preferences"
      ? preferences
      : {
          ...page,
          items: [{ ...note, stale: true, link: "https://outside.example" }],
        },
  );
  setup();
  expect(await screen.findByText(/no longer current/)).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Open details" }),
  ).not.toBeInTheDocument();
});
it("renders bounded pagination and an empty inbox", async () => {
  api.mockImplementation(async (path) =>
    path === "/notifications/preferences"
      ? preferences
      : path.includes("offset=20")
        ? { items: [], unread_count: 1, next_offset: null }
        : { ...page, next_offset: 20 },
  );
  setup();
  fireEvent.click(await screen.findByText("More notifications"));
  expect(
    await screen.findByText("No notifications here yet."),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/notifications?unread=false&offset=20");
});
it("exposes retry tools only on the superadmin inbox", async () => {
  api.mockImplementation(async (path) =>
    path === "/notifications/preferences"
      ? preferences
      : path.startsWith("/notifications/operations/failed")
        ? [
            {
              id: "j1",
              kind: "notification.email",
              attempts: 3,
              last_error: "RuntimeError",
            },
          ]
        : page,
  );
  setup("SUPER_ADMIN");
  fireEvent.click(await screen.findByText("Retry job"));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/notifications/operations/j1/retry", {
      method: "POST",
    }),
  );
  expect(
    screen.queryByLabelText("Daily coupon suggestions"),
  ).not.toBeInTheDocument();
});
