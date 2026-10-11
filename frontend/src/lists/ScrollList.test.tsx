import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { ScrollMore, useScrollQuery } from "./ScrollList";

type Page = {
  items: { id: string; title: string }[];
  next_offset: number | null;
};
const request = vi.fn<(filter: string, offset: number) => Promise<Page>>();
let observers: { callback: IntersectionObserverCallback; active: boolean }[];
beforeEach(() => {
  request.mockReset();
  observers = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      entry: (typeof observers)[number];
      constructor(callback: IntersectionObserverCallback) {
        this.entry = { callback, active: true };
        observers.push(this.entry);
      }
      observe() {}
      disconnect() {
        this.entry.active = false;
      }
    },
  );
});
afterEach(() => vi.unstubAllGlobals());
function enterViewport() {
  act(() =>
    observers
      .filter((o) => o.active)
      .forEach((o) =>
        o.callback(
          [{ isIntersecting: true } as IntersectionObserverEntry],
          {} as IntersectionObserver,
        ),
      ),
  );
}
function List({ scroll = true }: { scroll?: boolean }) {
  const [filter, setFilter] = useState("all");
  const query = useScrollQuery({
    queryKey: ["test-items", filter],
    field: "items",
    scroll,
    retry: false,
    queryFn: ({ pageParam }) => request(filter, pageParam),
  });
  return (
    <>
      <button onClick={() => setFilter("new")}>Change filter</button>
      {query.data?.items.map((i) => (
        <p key={i.id}>{i.title}</p>
      ))}
      {query.data && <ScrollMore query={query} label="items" />}
    </>
  );
}
function setup(scroll = true) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <List scroll={scroll} />
    </QueryClientProvider>,
  );
}
const first: Page = {
  items: [{ id: "1", title: "First result" }],
  next_offset: 12,
};
it("appends visible pages without duplicating existing results and stops at the end", async () => {
  request.mockResolvedValueOnce(first).mockResolvedValueOnce({
    items: [...first.items, { id: "2", title: "Second result" }],
    next_offset: null,
  });
  setup();
  await screen.findByText("First result");
  enterViewport();
  await screen.findByText("Second result");
  expect(screen.getAllByText("First result")).toHaveLength(1);
  expect(request).toHaveBeenLastCalledWith("all", 12);
  await screen.findByText("You’re all caught up on items.");
  enterViewport();
  expect(request).toHaveBeenCalledTimes(2);
});
it("keeps loaded results on failure and retries only the failed page", async () => {
  request
    .mockResolvedValueOnce(first)
    .mockRejectedValueOnce(new Error("Offline"))
    .mockResolvedValueOnce({
      items: [{ id: "2", title: "Recovered result" }],
      next_offset: null,
    });
  setup();
  await screen.findByText("First result");
  enterViewport();
  await screen.findByRole("alert");
  expect(screen.getByText("First result")).toBeInTheDocument();
  enterViewport();
  expect(request).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Retry loading items" }));
  await screen.findByText("Recovered result");
  expect(request).toHaveBeenLastCalledWith("all", 12);
});
it("isolates an in-flight old page when the filter changes", async () => {
  let resolve!: (page: Page) => void;
  request.mockImplementation(async (filter, offset) => {
    if (filter === "new")
      return {
        items: [{ id: "3", title: "Filtered result" }],
        next_offset: null,
      };
    if (offset === 0) return first;
    return new Promise<Page>((r) => {
      resolve = r;
    });
  });
  setup();
  await screen.findByText("First result");
  enterViewport();
  await waitFor(() => expect(request).toHaveBeenCalledWith("all", 12));
  enterViewport();
  expect(request).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByText("Change filter"));
  await screen.findByText("Filtered result");
  await act(async () =>
    resolve({ items: [{ id: "2", title: "Old response" }], next_offset: null }),
  );
  expect(screen.queryByText("Old response")).not.toBeInTheDocument();
  expect(screen.queryByText("First result")).not.toBeInTheDocument();
  expect(request).toHaveBeenLastCalledWith("new", 0);
});
it("provides a keyboard-accessible fallback without IntersectionObserver", async () => {
  vi.stubGlobal("IntersectionObserver", undefined);
  request.mockResolvedValueOnce(first).mockResolvedValueOnce({
    items: [{ id: "2", title: "Second result" }],
    next_offset: null,
  });
  setup();
  await screen.findByText("First result");
  fireEvent.click(screen.getByRole("button", { name: "More items" }));
  await screen.findByText("Second result");
});
it("does not automatically fetch management pages", async () => {
  request.mockResolvedValue(first);
  setup(false);
  await screen.findByText("First result");
  enterViewport();
  expect(request).toHaveBeenCalledTimes(1);
});
it.each([0, 10001])(
  "stops on a repeated or out-of-range next offset %s",
  async (next_offset) => {
    request.mockResolvedValue({ ...first, next_offset });
    setup();
    await screen.findByText("First result");
    enterViewport();
    expect(request).toHaveBeenCalledTimes(1);
  },
);
