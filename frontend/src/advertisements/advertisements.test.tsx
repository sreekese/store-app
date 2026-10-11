vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: null }) }));
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { raw } from "../auth/client";
import AdSlot, { AdCard, safeDestination } from "./AdSlot";
import type { Card, Placement } from "./types";
vi.mock("../auth/client", () => ({ raw: vi.fn() }));
const card: Card = {
  id: "ad1",
  sponsor: "Local shop",
  headline: "Explore nearby",
  body: "Fresh local deals",
  cta: "Explore",
  image_url: "",
  image_alt: "",
  placement: "BELOW_OFFERS",
  href: "/#discover",
  valid_until: "2030-01-01T00:00:00Z",
};
beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
function slot(placement: Placement = "BELOW_OFFERS") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <AdSlot placement={placement} />
    </QueryClientProvider>,
  );
}
it("labels sponsorship and uses only internal destinations", () => {
  render(<AdCard ad={card} />);
  expect(screen.getByLabelText("Sponsored by Local shop")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Explore" })).toHaveAttribute(
    "href",
    "/#discover",
  );
});
it.each([
  "https://example.com",
  "//example.com",
  "javascript:alert(1)",
  "/login",
  "/#discover?url=external",
])("rejects destination %s", (href) => {
  expect(safeDestination(href)).toBe(false);
  const { container } = render(<AdCard ad={{ ...card, href }} />);
  expect(container).toBeEmptyDOMElement();
});
it("preview cannot navigate into the shopper experience", () => {
  render(<AdCard ad={card} preview />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("Explore")).toBeInTheDocument();
});
it("failed creative keeps accessible sponsor text and CTA", () => {
  render(
    <AdCard
      ad={{
        ...card,
        image_url: "https://example.com/ad.png",
        image_alt: "Local shop front",
      }}
    />,
  );
  fireEvent.error(screen.getByAltText("Local shop front"));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByRole("link")).toBeInTheDocument();
});
it("renders eligible placement using server time", async () => {
  vi.mocked(raw).mockResolvedValue({
    server_time: "2029-01-01T00:00:00Z",
    items: [card],
  });
  slot();
  expect(
    await screen.findByRole("link", { name: "Explore" }),
  ).toBeInTheDocument();
});
it.each([
  { items: [] },
  { items: [{ ...card, placement: "BELOW_DAILY" }] },
  { items: [{ ...card, valid_until: "2028-01-01T00:00:00Z" }] },
])("hides empty, other-placement or expired inventory", async ({ items }) => {
  vi.mocked(raw).mockResolvedValue({
    server_time: "2029-01-01T00:00:00Z",
    items,
  });
  const { container } = slot();
  await vi.waitFor(() => expect(raw).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
it("API failure leaves no advertisement placeholder", async () => {
  vi.mocked(raw).mockRejectedValue(new Error("Unavailable"));
  const { container } = slot();
  await vi.waitFor(() => expect(raw).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("removes a displayed ad when its server-relative deadline passes", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const clock = vi.spyOn(performance, "now").mockReturnValue(0);
  vi.mocked(raw).mockResolvedValue({
    server_time: "2029-01-01T00:00:00Z",
    items: [{ ...card, valid_until: "2029-01-01T00:00:01Z" }],
  });
  slot();
  expect(
    await screen.findByRole("link", { name: "Explore" }),
  ).toBeInTheDocument();
  clock.mockReturnValue(1100);
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("shows every eligible ad in a placement and excludes other slots and unsafe links", async () => {
  vi.mocked(raw).mockResolvedValue({
    server_time: "2029-01-01T00:00:00Z",
    items: [
      { ...card, placement: "BELOW_HERO" },
      { ...card, id: "ad2", sponsor: "Second shop", placement: "BELOW_HERO" },
      { ...card, id: "ad3", sponsor: "Other slot", placement: "ABOVE_OFFERS" },
      { ...card, id: "ad4", sponsor: "Unsafe", href: "https://example.com" },
    ],
  });
  slot("BELOW_HERO");
  expect(
    await screen.findByLabelText("Sponsored by Second shop"),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Sponsored by Local shop")).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Sponsored by Other slot"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Sponsored by Unsafe"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: /scroll horizontally/ }),
  ).toHaveAttribute("tabindex", "0");
});

it.each(["BELOW_HERO", "ABOVE_OFFERS"] as const)(
  "renders the new %s placement",
  async (placement) => {
    vi.mocked(raw).mockResolvedValue({
      server_time: "2029-01-01T00:00:00Z",
      items: [{ ...card, placement }],
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AdSlot placement={placement} />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByLabelText("Sponsored by Local shop"),
    ).toBeInTheDocument();
  },
);

it("shows one banner at a time and supports dots and touch swipes without arrows", async () => {
  vi.mocked(raw).mockResolvedValue({
    server_time: "2029-01-01T00:00:00Z",
    items: [card, { ...card, id: "ad2", sponsor: "Second shop" }],
  });
  slot();
  await screen.findByLabelText("Sponsored by Local shop");
  expect(
    screen.queryByLabelText("Sponsored by Second shop"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Sponsored discoveries")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show advertisement 2" }));
  expect(screen.getByLabelText("Sponsored by Second shop")).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Sponsored by Local shop"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show advertisement 1" }));
  expect(screen.getByLabelText("Sponsored by Local shop")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show advertisement 2" }));
  fireEvent.click(screen.getByRole("button", { name: "Show advertisement 1" }));
  expect(
    screen.queryByRole("button", { name: "Next advertisement" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Previous advertisement" }),
  ).not.toBeInTheDocument();
  const slide = screen.getByLabelText("Sponsored by Local shop");
  fireEvent.touchStart(slide, { touches: [{ clientX: 250, clientY: 100 }] });
  fireEvent.touchEnd(slide, {
    changedTouches: [{ clientX: 80, clientY: 110 }],
  });
  expect(screen.getByLabelText("Sponsored by Second shop")).toBeInTheDocument();
});
