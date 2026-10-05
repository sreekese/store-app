import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import AdManager from "./AdManager";
vi.mock("../auth/client", () => ({ authorized: vi.fn(), raw: vi.fn() }));
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "super" } }),
}));
const api = vi.mocked(authorized);
const ad = {
  id: "a1",
  revision: 3,
  status: "DRAFT",
  sponsor: "Local shop",
  headline: "Local discovery",
  body: "Find nearby deals",
  image_url: "",
  image_alt: "",
  cta: "Explore",
  placement: "BELOW_OFFERS",
  destination_type: "DISCOVER",
  store_id: null,
  offer_id: null,
  starts_at: "2029-01-01T00:00:00Z",
  expires_at: "2029-01-02T00:00:00Z",
};
let overlap = false;
beforeEach(() => {
  vi.resetAllMocks();
  overlap = false;
  api.mockImplementation(async (path, options) => {
    if (path.endsWith("/preview"))
      return {
        card: { ...ad, href: "/#discover", valid_until: ad.expires_at },
        preview_token: "preview-proof",
        overlap,
        destination_available_now: true,
      };
    if (path.endsWith("/actions"))
      return { ...ad, status: "ENABLED", revision: 4 };
    if (path === "/advertisements/manage/a1" && options?.method === "PUT")
      return { ...ad, ...JSON.parse(options.body as string), revision: 4 };
    if (path === "/advertisements/manage/a1") return { ...ad, revision: 4 };
    if (path.startsWith("/advertisements/manage?"))
      return { items: [ad], next_offset: null };
    return [];
  });
});
async function setup() {
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
        <AdManager />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Manage Local discovery" }),
  );
}
it("requires saved preview and submits its proof with the current revision", async () => {
  await setup();
  expect(
    screen.queryByRole("button", { name: "Enable advertisement" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Preview saved ad" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Enable advertisement" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/advertisements/manage/a1/actions", {
      method: "POST",
      body: JSON.stringify({
        revision: 3,
        action: "ENABLE",
        preview_token: "preview-proof",
      }),
    }),
  );
  expect(
    await screen.findByText("Advertisement saved as ENABLED."),
  ).toBeInTheDocument();
});
it("unsaved changes clear preview and require saving again", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "Preview saved ad" }));
  await screen.findByRole("button", { name: "Enable advertisement" });
  fireEvent.change(screen.getByLabelText("Headline"), {
    target: { value: "Changed headline" },
  });
  expect(
    screen.getByRole("button", { name: "Preview saved ad" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Enable advertisement" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
  expect(
    await screen.findByText("Advertisement saved as DRAFT."),
  ).toBeInTheDocument();
});
it("overlap preview blocks publication", async () => {
  overlap = true;
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "Preview saved ad" }));
  expect(
    await screen.findByRole("button", { name: "Enable advertisement" }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("overlaps");
});
it("reload retrieves the current saved revision", async () => {
  await setup();
  fireEvent.click(screen.getByRole("button", { name: "Reload saved ad" }));
  expect(
    await screen.findByText("Saved state: DRAFT · revision 4"),
  ).toBeInTheDocument();
});
it("status filter requests the matching first page", async () => {
  await setup();
  fireEvent.change(screen.getByLabelText("Ad status"), {
    target: { value: "ARCHIVED" },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/advertisements/manage?offset=0&status=ARCHIVED",
    ),
  );
});
