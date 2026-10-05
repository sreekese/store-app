import { TrackView, sendEvent } from "../analytics/tracking";
import { useAuth } from "../auth/AuthProvider";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { raw } from "../auth/client";
import type { Card, Placement } from "./types";
const uuid = "[0-9a-fA-F-]{36}";
export function safeDestination(href: string) {
  return (
    href === "/#discover" ||
    new RegExp(`^/stores/${uuid}$`).test(href) ||
    new RegExp(`^/offers/${uuid}\\?store_id=${uuid}$`).test(href)
  );
}
export function AdCard({
  ad,
  preview = false,
  track = false,
}: {
  ad: Card;
  preview?: boolean;
  track?: boolean;
}) {
  const [failed, setFailed] = useState("");
  if (!safeDestination(ad.href)) return null;
  const showImage = !!ad.image_url && failed !== ad.image_url;
  return (
    <aside
      className={`sponsored-card${showImage ? " with-creative" : ""}`}
      aria-label={`Sponsored by ${ad.sponsor}`}
    >
      {track && !preview && <TrackView kind="AD_VIEWED" id={ad.id} />}
      <div>
        <p className="sponsored-label">Sponsored · {ad.sponsor}</p>
        <h3>{ad.headline}</h3>
        <p>{ad.body}</p>
        {preview ? (
          <span className="button secondary">{ad.cta}</span>
        ) : (
          <a
            className="button secondary"
            href={ad.href}
            onClick={() => {
              if (track) sendEvent("AD_CLICKED", ad.id);
            }}
          >
            {ad.cta}
          </a>
        )}
      </div>
      {showImage && (
        <img
          src={ad.image_url}
          alt={ad.image_alt}
          width="640"
          height="360"
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(ad.image_url)}
        />
      )}
    </aside>
  );
}
export default function AdSlot({ placement }: { placement: Placement }) {
  const auth = useAuth();
  const [, tick] = useState(0);
  const query = useQuery({
    queryKey: ["shopper-advertisements"],
    queryFn: async () => {
      const receivedAt = performance.now();
      const page = await raw<{ server_time: string; items: Card[] }>(
        "/advertisements",
      );
      return { page, receivedAt };
    },
    retry: false,
    refetchInterval: 30000,
    gcTime: 0,
  });
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    const refresh = () => {
      if (!document.hidden) void query.refetch();
    };
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [query.refetch]);
  if (!query.data || query.isError) return null;
  const now =
    Date.parse(query.data.page.server_time) +
    performance.now() -
    query.data.receivedAt;
  const ad = query.data.page.items.find(
    (a) => a.placement === placement && Date.parse(a.valid_until) > now,
  );
  return ad ? (
    <AdCard key={ad.id} ad={ad} track={auth.user?.role === "USER"} />
  ) : null;
}
