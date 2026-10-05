import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { authorized, clearAccessToken, restoreSession } from "./client";
const data = {
  access_token: "new-access",
  user: { id: "1", role: "USER" },
  expires_in: 900,
};
const reply = (status: number, body: unknown) => ({
  ok: status === 200,
  status,
  headers: new Headers({ "Content-Type": "application/json" }),
  json: async () => body,
});
beforeEach(() => clearAccessToken());
afterEach(() => vi.unstubAllGlobals());
it("coalesces concurrent refresh requests", async () => {
  const fetch = vi.fn().mockResolvedValue(reply(200, data));
  vi.stubGlobal("fetch", fetch);
  const [one, two] = await Promise.all([restoreSession(), restoreSession()]);
  expect(one).toEqual(two);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("refreshes once after an expired access token and retries with new token", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(reply(401, {}))
    .mockResolvedValueOnce(reply(200, data))
    .mockResolvedValueOnce(reply(200, { id: "1" }));
  vi.stubGlobal("fetch", fetch);
  expect(await authorized("/auth/me")).toEqual({ id: "1" });
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls[2][1].headers.Authorization).toBe(
    "Bearer new-access",
  );
});
it("does not loop on an expired refresh session", async () => {
  const fetch = vi.fn().mockResolvedValue(reply(401, {}));
  vi.stubGlobal("fetch", fetch);
  await expect(authorized("/auth/me")).rejects.toThrow("Your session ended");
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("does not refresh after a role denial", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(reply(403, { error: { message: "Forbidden" } }));
  vi.stubGlobal("fetch", fetch);
  await expect(authorized("/workspaces/superadmin")).rejects.toThrow(
    "Forbidden",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("preserves a mutation body and method when refreshing an expired session", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(reply(401, {}))
    .mockResolvedValueOnce(reply(200, data))
    .mockResolvedValueOnce(reply(200, { saved: true }));
  vi.stubGlobal("fetch", fetch);
  const body = JSON.stringify({ display_name: "Neha" });
  await expect(
    authorized("/profile", { method: "PUT", body }),
  ).resolves.toEqual({ saved: true });
  expect(fetch.mock.calls[0][1].method).toBe("PUT");
  expect(fetch.mock.calls[2][1].method).toBe("PUT");
  expect(fetch.mock.calls[2][1].body).toBe(body);
  expect(fetch.mock.calls[2][1].headers["X-CSRF-Protection"]).toBe("1");
});
it("downloads CSV through authentication refresh", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(reply(401, {}))
    .mockResolvedValueOnce(reply(200, data))
    .mockResolvedValueOnce(
      new Response("date,claims\n2026-10-05,1\n", {
        headers: { "Content-Type": "text/csv; charset=utf-8" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  expect(await authorized<string>("/analytics/export")).toBe(
    "date,claims\n2026-10-05,1\n",
  );
  expect(fetch.mock.calls[2][1].headers.Authorization).toBe(
    "Bearer new-access",
  );
});
