import { TrackView, sendEvent } from "../analytics/tracking";
import { useAuth } from "../auth/AuthProvider";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { raw } from "../auth/client";
import { placements, type Card, type Placement } from "./types";
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
function BannerSlider({ ads, track }: { ads: Card[]; track: boolean }) {
  const [selected, setSelected] = useState(ads[0].id);
  const start = useRef<{ x: number; y: number } | null>(null);
  const index = Math.max(
    0,
    ads.findIndex((ad) => ad.id === selected),
  );
  const move = (direction: number) =>
    setSelected(ads[(index + direction + ads.length) % ads.length].id);
  return (
    <div
      className="ad-banner"
      role="region"
      aria-roledescription="carousel"
      aria-label="Advertisement banner"
    >
      <div
        onTouchStart={(event) => {
          const touch = event.touches[0];
          start.current = { x: touch.clientX, y: touch.clientY };
        }}
        onTouchCancel={() => {
          start.current = null;
        }}
        onTouchEnd={(event) => {
          const touch = event.changedTouches[0];
          if (start.current) {
            const dx = touch.clientX - start.current.x;
            const dy = touch.clientY - start.current.y;
            if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy))
              move(dx < 0 ? 1 : -1);
          }
          start.current = null;
        }}
      >
        <AdCard key={ads[index].id} ad={ads[index]} track={track} />
      </div>
      {ads.length > 1 && (
        <div className="ad-banner-controls">
          <div
            className="ad-banner-dots"
            role="group"
            aria-label="Choose advertisement"
          >
            {ads.map((ad, i) => (
              <button
                type="button"
                key={ad.id}
                aria-label={`Show advertisement ${i + 1}`}
                aria-pressed={i === index}
                onClick={() => setSelected(ad.id)}
              >
                <span aria-hidden="true" />
              </button>
            ))}
          </div>
          <span className="ad-banner-count" role="status" aria-live="polite">
            {index + 1} / {ads.length}
          </span>
        </div>
      )}
    </div>
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
  const ads = query.data.page.items.filter(
    (a) =>
      a.placement === placement &&
      Date.parse(a.valid_until) > now &&
      safeDestination(a.href),
  );
  if (!ads.length) return null;
  return (
    <section
      className="ad-placement"
      aria-label={`Sponsored · ${placements[placement]}`}
    >
      {placement !== "BELOW_HERO" ? (
        <BannerSlider ads={ads} track={auth.user?.role === "USER"} />
      ) : (
        <>
          {ads.length > 1 && (
            <div className="section-heading">
              <p className="eyebrow">Sponsored discoveries</p>
            </div>
          )}
          <div
            className={ads.length > 1 ? "ad-rail" : "ad-single"}
            tabIndex={ads.length > 1 ? 0 : undefined}
            role={ads.length > 1 ? "region" : undefined}
            aria-label={
              ads.length > 1
                ? "Sponsored ads; scroll horizontally for more"
                : undefined
            }
          >
            {ads.map((ad) => (
              <AdCard key={ad.id} ad={ad} track={auth.user?.role === "USER"} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
