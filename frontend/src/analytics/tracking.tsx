import { useEffect, useRef } from "react";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
type Kind =
  | "OFFER_VIEWED"
  | "STORE_VIEWED"
  | "COUPON_VIEWED"
  | "AD_VIEWED"
  | "AD_CLICKED";
export function sendEvent(kind: Kind, target_id: string) {
  void authorized("/analytics/events", {
    method: "POST",
    body: JSON.stringify({ kind, target_id }),
    keepalive: true,
  }).catch(() => {});
}
export function TrackView({ kind, id }: { kind: Kind; id: string }) {
  const auth = useAuth(),
    node = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (
      auth.user?.role !== "USER" ||
      !node.current ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    let sent = false;
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          !sent &&
          !document.hidden &&
          entries.some((e) => e.isIntersecting)
        ) {
          sent = true;
          sendEvent(kind, id);
          observer.disconnect();
        }
      },
      { threshold: 0 },
    );
    observer.observe(node.current);
    return () => observer.disconnect();
  }, [auth.user?.id, auth.user?.role, kind, id]);
  return <span ref={node} className="analytics-marker" aria-hidden="true" />;
}
