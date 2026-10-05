import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { authorized } from "../auth/client";
import RedemptionDesk from "./RedemptionDesk";
import Scanner from "./Scanner";
vi.mock("../auth/client", () => ({ authorized: vi.fn() }));
const camera = vi.hoisted(() => ({ decode: vi.fn(), stop: vi.fn() }));
vi.mock("@zxing/browser", () => ({
  BrowserQRCodeReader: class {
    decodeFromStream(...args: unknown[]) {
      return camera.decode(...args);
    }
  },
}));
const api = vi.mocked(authorized),
  code = "private-opaque-coupon-token-for-test";
const preview = {
  claim_id: "c1",
  title: "Saved lunch",
  store_name: "Central",
  expires_at: "2027-01-01T12:00:00Z",
  offer: { terms_conditions: "Dine-in only" },
  purchase_amount: "250.00",
  discount_amount: "50.00",
  payable_amount: "200.00",
  confirmation_token: "signed-preview",
  confirm_before: "2027-01-01T11:05:00Z",
};
const receipt = {
  id: "r1",
  claim_id: "c1",
  title: "Saved lunch",
  store_name: "Central",
  redeemed_at: "2027-01-01T11:00:00Z",
  purchase_amount: "250.00",
  discount_amount: "50.00",
  payable_amount: "200.00",
  currency: "INR",
};
function setup(staff = false) {
  return render(
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
      <RedemptionDesk staff={staff} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  api.mockReset();
  camera.decode.mockReset();
  camera.stop.mockReset();
  camera.decode.mockResolvedValue({ stop: camera.stop });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi
        .fn()
        .mockResolvedValue({ getTracks: () => [{ stop: camera.stop }] }),
    },
  });
  api.mockImplementation(async (path) => {
    if (path.endsWith("/stores"))
      return [{ id: "s1", name: "Central", city: "Kochi", status: "ACTIVE" }];
    if (path === "/redemptions/validate") return preview;
    if (path === "/redemptions") return receipt;
    if (path.startsWith("/redemptions?")) return [];
    throw Error("Unexpected endpoint");
  });
});
async function fill() {
  await screen.findByRole("option", { name: "Central · Kochi" });
  fireEvent.change(screen.getByLabelText("Redemption branch"), {
    target: { value: "s1" },
  });
  fireEvent.change(screen.getByLabelText("Manual coupon code"), {
    target: { value: code },
  });
  fireEvent.change(screen.getByLabelText("Eligible original total (₹)"), {
    target: { value: "250" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Validate coupon" }));
  await screen.findByRole("heading", { name: "Saved lunch" });
}
it("validation does not redeem and explicit acknowledgement is required", async () => {
  setup();
  await fill();
  expect(screen.getByText("₹50.00")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Confirm redemption" }),
  ).toBeDisabled();
  expect(api.mock.calls.some(([p]) => p === "/redemptions")).toBe(false);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm redemption" }));
  expect(
    await screen.findByRole("heading", { name: "Coupon redeemed" }),
  ).toBeInTheDocument();
  const request = api.mock.calls.find(([p]) => p === "/redemptions")![1]!;
  expect(JSON.parse(request.body as string)).toEqual({
    store_id: "s1",
    claim_token: code,
    purchase_amount: "250",
    reward_value: null,
    confirmation_token: "signed-preview",
    terms_confirmed: true,
  });
  expect(
    (request.headers as Record<string, string>)["Idempotency-Key"],
  ).toMatch(/^[a-f0-9-]{36}$/);
  expect(screen.getByLabelText("Manual coupon code")).toHaveValue("");
});
it("editing an amount discards the previous confirmation", async () => {
  setup();
  await fill();
  fireEvent.change(screen.getByLabelText("Eligible original total (₹)"), {
    target: { value: "500" },
  });
  expect(
    screen.queryByRole("button", { name: "Confirm redemption" }),
  ).not.toBeInTheDocument();
});
it("ambiguous retry keeps the same request key and no false success", async () => {
  let count = 0;
  api.mockImplementation(async (path) => {
    if (path.endsWith("/stores"))
      return [{ id: "s1", name: "Central", city: "Kochi", status: "ACTIVE" }];
    if (path === "/redemptions/validate") return preview;
    if (path === "/redemptions") {
      if (++count === 1) throw Error("Network interrupted; retry safely");
      return receipt;
    }
    return [];
  });
  setup();
  await fill();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm redemption" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Network interrupted",
  );
  expect(
    screen.queryByRole("heading", { name: "Coupon redeemed" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm redemption" }));
  await screen.findByRole("heading", { name: "Coupon redeemed" });
  const calls = api.mock.calls.filter(([p]) => p === "/redemptions");
  expect(calls[0][1]?.headers).toEqual(calls[1][1]?.headers);
});
it("staff use current assigned branches and own activity history", async () => {
  setup(true);
  await fill();
  expect(api).toHaveBeenCalledWith("/staff/stores");
  expect(
    screen.getByText(/Your redemptions at your currently assigned branch/),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/redemptions?store_id=s1&offset=0");
});
it("validation denial cannot be confirmed", async () => {
  api.mockImplementation(async (path) => {
    if (path.endsWith("/stores"))
      return [{ id: "s1", name: "Central", city: "Kochi", status: "ACTIVE" }];
    if (path === "/redemptions/validate") throw Error("Coupon expired");
    return [];
  });
  setup();
  await screen.findByRole("option", { name: "Central · Kochi" });
  fireEvent.change(screen.getByLabelText("Redemption branch"), {
    target: { value: "s1" },
  });
  fireEvent.change(screen.getByLabelText("Manual coupon code"), {
    target: { value: code },
  });
  fireEvent.change(screen.getByLabelText("Eligible original total (₹)"), {
    target: { value: "250" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Validate coupon" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Coupon expired");
  expect(
    screen.queryByRole("button", { name: "Confirm redemption" }),
  ).not.toBeInTheDocument();
});
it("camera is requested only after an explicit scan action", async () => {
  setup();
  await screen.findByRole("option", { name: "Central · Kochi" });
  expect(camera.decode).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Scan QR code" }));
  await waitFor(() => expect(camera.decode).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "Stop camera" }));
  expect(camera.stop).toHaveBeenCalled();
});
it("permission denial keeps manual entry available", async () => {
  camera.decode.mockRejectedValue(new Error("NotAllowedError"));
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Scan QR code" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Use the manual coupon code",
  );
  expect(screen.getByLabelText("Manual coupon code")).toBeInTheDocument();
});
it("scanning accepts an opaque token without automatically validating", async () => {
  const onRead = vi.fn();
  const view = render(<Scanner onRead={onRead} />);
  await waitFor(() => expect(camera.decode).toHaveBeenCalled());
  const callback = camera.decode.mock.calls[0][2];
  act(() => callback({ getText: () => code }, null, { stop: camera.stop }));
  expect(onRead).toHaveBeenCalledWith(code);
  expect(camera.stop).toHaveBeenCalled();
  expect(api).not.toHaveBeenCalled();
  view.unmount();
});
it("unrelated QR content is rejected without navigating to its URL", async () => {
  const onRead = vi.fn();
  render(<Scanner onRead={onRead} />);
  await waitFor(() => expect(camera.decode).toHaveBeenCalled());
  act(() =>
    camera.decode.mock.calls[0][2](
      { getText: () => "https://example.com/not-a-coupon" },
      null,
      { stop: camera.stop },
    ),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("not a coupon QR");
  expect(onRead).not.toHaveBeenCalled();
});
it("camera acquired after unmount is stopped immediately", async () => {
  let finish!: (c: { stop: () => void }) => void;
  camera.decode.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(<Scanner onRead={vi.fn()} />);
  view.unmount();
  await act(async () => finish({ stop: camera.stop }));
  expect(camera.stop).toHaveBeenCalled();
});

it("stops a stream immediately while decoder initialization is still pending", async () => {
  let finish!: (c: { stop: () => void }) => void;
  camera.decode.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(<Scanner onRead={vi.fn()} />);
  await waitFor(() => expect(camera.decode).toHaveBeenCalled());
  view.unmount();
  expect(camera.stop).toHaveBeenCalled();
  await act(async () => finish({ stop: camera.stop }));
  expect(camera.stop.mock.calls.length).toBeGreaterThan(1);
});
