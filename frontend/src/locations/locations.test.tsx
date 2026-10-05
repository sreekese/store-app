vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: null }) }));
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { raw, authorized } from "../auth/client";
import Discover from "./Discover";
import BranchManager from "./BranchManager";
import type { ReactNode } from "react";
vi.mock("../daily/DailyCoupons", () => ({ default: () => null }));
vi.mock("../offers/OfferBrowser", () => ({ default: () => null }));
vi.mock("../auth/client", () => ({ raw: vi.fn(), authorized: vi.fn() }));
const publicApi = vi.mocked(raw),
  privateApi = vi.mocked(authorized);
const config = { default_radius_km: 5, max_radius_km: 10 };
const place = {
  id: "s1",
  label: "Fort Kochi, Kochi, Kerala, IN",
  reference_name: "Central branch",
  latitude: 9.965,
  longitude: 76.242,
};
const store = {
  id: "s1",
  merchant_id: "m1",
  name: "Central branch",
  business_name: "Demo Café",
  category: "Café",
  address: "Market Road",
  city: "Kochi",
  area: "Fort Kochi",
  state: "Kerala",
  country: "IN",
  postal_code: "682001",
  phone: "9876543210",
  timezone: "Asia/Kolkata",
  latitude: 9.965,
  longitude: 76.242,
  hours: [],
  is_open: null,
  distance_meters: 1000,
  status: "ACTIVE",
  revision: 2,
  updated_at: "2026-09-27T12:00:00Z",
};
const results = (stores: unknown[] = [store]) => ({
  centre: { type: "Point", coordinates: [76.242, 9.965] },
  radius_km: 5,
  stores,
  next_offset: null,
});
function setup(node: ReactNode = <Discover />) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>,
  );
}
function mockPublic(empty = false) {
  publicApi.mockImplementation(async (path) => {
    if (path === "/locations/config") return config;
    if (path.startsWith("/locations/places")) return [place];
    if (path.startsWith("/locations/nearby"))
      return results(empty ? [] : [store]);
    if (path.startsWith("/locations/stores/")) return store;
    throw new Error("Unexpected " + path);
  });
}
async function manualSearch() {
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use my location" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("City or area"), {
    target: { value: "Kochi" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find places" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Fort Kochi, Kochi/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Search around this place" }),
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  mockPublic();
});
afterEach(() => vi.unstubAllGlobals());
it("does not request location permission automatically", async () => {
  const getCurrentPosition = vi.fn();
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: { getCurrentPosition },
  });
  setup();
  await screen.findByText("Find stores near you.");
  expect(getCurrentPosition).not.toHaveBeenCalled();
  expect(publicApi.mock.calls.every(([path]) => !path.includes("nearby"))).toBe(
    true,
  );
});
it("requires confirmation of a manual reference point and searches 5 km", async () => {
  setup();
  await manualSearch();
  expect(
    await screen.findByText("Central branch", { selector: "h3" }),
  ).toBeInTheDocument();
  expect(screen.getByText("1.00 km away")).toBeInTheDocument();
  expect(
    screen.getByText(/Approximate straight-line distance/),
  ).toBeInTheDocument();
  expect(publicApi).toHaveBeenCalledWith(
    "/locations/nearby?latitude=9.965&longitude=76.242&radius_km=5&offset=0&limit=12",
  );
});
it("GPS denial leaves manual selection available", async () => {
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: (
        _success: unknown,
        error: (value: { code: number }) => void,
      ) => error({ code: 1 }),
    },
  });
  setup();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use my location" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "permission was denied",
  );
  await manualSearch();
  expect(await screen.findByText("1.00 km away")).toBeInTheDocument();
});
it("GPS success searches its coordinates and shows the centre", async () => {
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: (
        success: (value: {
          coords: { latitude: number; longitude: number };
        }) => void,
      ) => success({ coords: { latitude: 10, longitude: 76 } }),
    },
  });
  setup();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use my location" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));
  expect(await screen.findByText("Your current location")).toBeInTheDocument();
  expect(publicApi).toHaveBeenCalledWith(
    "/locations/nearby?latitude=10&longitude=76&radius_km=5&offset=0&limit=12",
  );
});
it("a late GPS result cannot overwrite a manually chosen place", async () => {
  let complete!: (value: {
    coords: { latitude: number; longitude: number };
  }) => void;
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: (success: typeof complete) => {
        complete = success;
      },
    },
  });
  setup();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use my location" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Use my location" }));
  fireEvent.change(screen.getByLabelText("City or area"), {
    target: { value: "Kochi" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find places" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Fort Kochi, Kochi/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Search around this place" }),
  );
  await screen.findByText("1.00 km away");
  act(() => complete({ coords: { latitude: 0, longitude: 0 } }));
  expect(screen.queryByText("Your current location")).not.toBeInTheDocument();
  expect(
    publicApi.mock.calls.filter(([path]) => path.includes("nearby")).length,
  ).toBe(1);
});
it("does not expand an empty search until explicitly requested", async () => {
  mockPublic(true);
  setup();
  await manualSearch();
  expect(
    await screen.findByText("No stores found in this radius."),
  ).toBeInTheDocument();
  expect(
    publicApi.mock.calls.some(([path]) => path.includes("radius_km=10")),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Expand to 10 km" }));
  await waitFor(() =>
    expect(
      publicApi.mock.calls.some(([path]) => path.includes("radius_km=10")),
    ).toBe(true),
  );
});
it("empty manual catalogue explains coordinate fallback", async () => {
  publicApi.mockImplementation(async (path) =>
    path === "/locations/config"
      ? config
      : path === "/advertisements"
        ? { server_time: new Date().toISOString(), items: [] }
        : [],
  );
  setup();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use my location" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("City or area"), {
    target: { value: "Unknown town" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find places" }));
  expect(
    await screen.findByText(/No listed reference points found/),
  ).toBeInTheDocument();
});
it("explicit coordinates accept zero latitude and longitude", async () => {
  setup();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Search this map point" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("Search latitude"), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText("Search longitude"), {
    target: { value: "0" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Search this map point" }),
  );
  await waitFor(() =>
    expect(publicApi).toHaveBeenCalledWith(
      "/locations/nearby?latitude=0&longitude=0&radius_km=5&offset=0&limit=12",
    ),
  );
});
it("failed nearby requests offer retry without showing an empty result", async () => {
  publicApi.mockImplementation(async (path) => {
    if (path === "/locations/config") return config;
    if (path.includes("/places")) return [place];
    throw new Error("Search unavailable");
  });
  setup();
  await manualSearch();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Search unavailable",
  );
  expect(
    screen.queryByText("No stores found in this radius."),
  ).not.toBeInTheDocument();
  mockPublic();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("1.00 km away")).toBeInTheDocument();
});
it("store details recheck availability and display hours", async () => {
  const base = publicApi.getMockImplementation()!;
  publicApi.mockImplementation(async (path, options) =>
    path.includes("/stores/")
      ? {
          ...store,
          hours: [
            {
              day_of_week: 0,
              is_closed: false,
              open_time: "20:00",
              close_time: "02:00",
              closes_next_day: true,
            },
          ],
        }
      : base(path, options),
  );
  setup();
  await manualSearch();
  fireEvent.click(
    await screen.findByRole("button", { name: "View details: Central branch" }),
  );
  expect(await screen.findByText("20:00–02:00 (next day)")).toBeInTheDocument();
  expect(screen.getByText("Store timezone: Asia/Kolkata")).toBeInTheDocument();
});
it("branch editing sends revision, coordinates, and weekly closed days", async () => {
  privateApi.mockImplementation(async (_path, options) =>
    options?.method === "PUT" ? store : [store],
  );
  setup(<BranchManager suspended={false} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit branch: Central branch" }),
  );
  fireEvent.change(screen.getByLabelText("Latitude"), {
    target: { value: "10" },
  });
  fireEvent.click(screen.getByLabelText("Publish weekly hours"));
  fireEvent.click(screen.getByLabelText("Closed Sunday"));
  fireEvent.click(screen.getByRole("button", { name: "Save branch" }));
  expect(await screen.findByText("Branch updated.")).toBeInTheDocument();
  const call = privateApi.mock.calls.find(
    ([, options]) => options?.method === "PUT",
  )!;
  const body = JSON.parse(call[1]!.body as string);
  expect(call[0]).toBe("/merchant/stores/s1");
  expect(body.revision).toBe(2);
  expect(body.latitude).toBe(10);
  expect(body.hours[6]).toEqual({
    day_of_week: 6,
    is_closed: true,
    open_time: null,
    close_time: null,
    closes_next_day: false,
  });
  expect(body.hours.length).toBe(7);
  expect(body).not.toHaveProperty("merchant_id");
});
it("branch save conflicts preserve edits and provide reload", async () => {
  privateApi.mockImplementation(async (_path, options) => {
    if (options?.method === "PUT")
      throw new Error("This branch changed. Reload branches before saving.");
    return [store];
  });
  setup(<BranchManager suspended={false} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit branch: Central branch" }),
  );
  fireEvent.change(screen.getByLabelText("Branch name"), {
    target: { value: "Changed name" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save branch" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This branch changed",
  );
  expect(screen.getByLabelText("Branch name")).toHaveValue("Changed name");
  fireEvent.click(screen.getByRole("button", { name: "Reload branches" }));
  expect(screen.getByLabelText("Branch name")).toHaveValue("");
});
it("branch deactivation is explicit and retains the branch ID", async () => {
  privateApi.mockImplementation(async (_path, options) =>
    options?.method === "PUT" ? { ...store, status: "INACTIVE" } : [store],
  );
  setup(<BranchManager suspended={false} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Edit branch: Central branch" }),
  );
  fireEvent.change(screen.getByLabelText("Branch status"), {
    target: { value: "INACTIVE" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save branch" }));
  await screen.findByText("Branch updated.");
  const call = privateApi.mock.calls.find(
    ([, options]) => options?.method === "PUT",
  )!;
  expect(call[0]).toBe("/merchant/stores/s1");
  expect(JSON.parse(call[1]!.body as string).status).toBe("INACTIVE");
});
it("a suspended merchant cannot edit a branch", async () => {
  privateApi.mockResolvedValue([store]);
  setup(<BranchManager suspended />);
  expect(
    await screen.findByRole("button", { name: "Edit branch: Central branch" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Add branch" })).toBeDisabled();
});
it("assigned inactive stores can be deselected but cannot be newly assigned", async () => {
  const { StoreChoices } = await import("../profiles/shared");
  const inactive = { ...store, status: "INACTIVE" as const };
  const onChange = vi.fn();
  const view = setup(
    <StoreChoices stores={[inactive]} selected={["s1"]} onChange={onChange} />,
  );
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).toBeEnabled();
  fireEvent.click(checkbox);
  expect(onChange).toHaveBeenCalledWith([]);
  view.unmount();
  setup(<StoreChoices stores={[inactive]} selected={[]} onChange={onChange} />);
  expect(screen.getByRole("checkbox")).toBeDisabled();
});
