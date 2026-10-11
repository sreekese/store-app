import { useEffect, useRef } from "react";
import { useInfiniteQuery, type QueryKey } from "@tanstack/react-query";

// Keep API page sizes bounded; only request another page when it is needed.
export function useScrollQuery<T>({
  field,
  pageSize = 25,
  initialOffset = 0,
  scroll = true,
  ...options
}: {
  queryKey: QueryKey;
  queryFn: (context: { pageParam: number }) => Promise<T>;
  field?: keyof T;
  pageSize?: number;
  initialOffset?: number;
  scroll?: boolean;
  enabled?: boolean;
  retry?: false;
  refetchInterval?: number;
  gcTime?: number;
}) {
  const query = useInfiniteQuery({
    ...options,
    queryKey: [...options.queryKey, "scroll-list", scroll, initialOffset],
    initialPageParam: initialOffset,
    getNextPageParam: (last, _pages, offset) => {
      if (!scroll) return undefined;
      const next = Array.isArray(last)
        ? last.length === pageSize
          ? offset + pageSize
          : null
        : (last as { next_offset: number | null }).next_offset;
      return next != null && next > offset && next <= 10000 ? next : undefined;
    },
  });
  const pages = query.data?.pages;
  let data: T | undefined;
  if (pages?.length) {
    const seen = new Set<string>();
    const items = pages
      .flatMap(
        (page) =>
          (field ? page[field] : page) as unknown as Record<string, unknown>[],
      )
      .filter((item) => {
        const key = String(item.id ?? `${item.campaign_id}:${item.store_id}`);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    data = (field ? { ...pages[0], [field]: items } : items) as T;
  }
  return {
    ...query,
    data,
    // A failed later page must not erase the cards already on screen.
    isError: query.isError && !query.isFetchNextPageError,
    error: query.isFetchNextPageError ? null : query.error,
  };
}

export function ScrollMore({
  query,
  label,
}: {
  query: {
    hasNextPage: boolean;
    isFetching: boolean;
    isFetchNextPageError: boolean;
    fetchNextPage: (options: { cancelRefetch: boolean }) => Promise<unknown>;
  };
  label: string;
}) {
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } =
    query;
  useEffect(() => {
    if (
      !hasNextPage ||
      isFetching ||
      isFetchNextPageError ||
      !sentinel.current ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void fetchNextPage({ cancelRefetch: false });
        }
      },
      { rootMargin: "200px 0px" },
    );
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
  return (
    <div ref={sentinel} className="scroll-more">
      {isFetchNextPageError && (
        <p role="alert">
          Couldn’t load more {label}. Your loaded items are still here.
        </p>
      )}
      <p role="status" aria-live="polite">
        {isFetching
          ? `Loading ${label}…`
          : !hasNextPage
            ? `You’re all caught up on ${label}.`
            : ""}
      </p>
      {hasNextPage && (
        <button
          className="text-button"
          disabled={isFetching}
          onClick={() => void fetchNextPage({ cancelRefetch: false })}
        >
          {isFetchNextPageError ? `Retry loading ${label}` : `More ${label}`}
        </button>
      )}
    </div>
  );
}
