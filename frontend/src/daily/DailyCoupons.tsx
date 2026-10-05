import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { authorized } from "../auth/client";
import { QueryState, Feedback } from "../profiles/shared";
interface Card {
  campaign_id: string;
  offer_id: string;
  store_id: string;
  title: string;
  store_name: string;
  distance_meters: number;
}
interface Result {
  recommendation: Card | null;
  daily_picks: Card[];
  next_offset: number | null;
  allowance: {
    remaining: number;
    limit: number;
    period: string;
    timezone: string;
    resets_at: string;
  };
}
export default function DailyCoupons({
  latitude,
  longitude,
  radius,
  maxRadius,
  onExpand,
}: {
  latitude: number;
  longitude: number;
  radius: number;
  maxRadius?: number;
  onExpand?: () => void;
}) {
  const auth = useAuth(),
    navigate = useNavigate(),
    client = useQueryClient();
  const [offset, setOffset] = useState(0),
    keys = useRef<Record<string, string>>({});
  const query = useQuery({
    queryKey: [
      "daily-coupons",
      auth.user?.id,
      latitude,
      longitude,
      radius,
      offset,
    ],
    queryFn: () =>
      authorized<Result>("/daily/recommendations", {
        method: "POST",
        body: JSON.stringify({
          latitude,
          longitude,
          radius_km: radius,
          offset,
        }),
      }),
    enabled: auth.user?.role === "USER",
    retry: false,
    refetchInterval: 30000,
    gcTime: 0,
  });
  const claim = useMutation({
    mutationFn: (id: string) => {
      keys.current[id] ||= crypto.randomUUID();
      return authorized<{ id: string }>(`/shopper/campaigns/${id}/claim`, {
        method: "POST",
        headers: { "Idempotency-Key": keys.current[id] },
      });
    },
    onSuccess: (r) => {
      void client.invalidateQueries({ queryKey: ["daily-coupons"] });
      void client.invalidateQueries({ queryKey: ["claim-allowance"] });
      navigate(`/app/coupons/${r.id}`);
    },
    onError: () => {
      void query.refetch();
    },
  });
  if (auth.user?.role !== "USER")
    return (
      <p>
        <Link to="/login">Sign in</Link> for your daily recommendation.
      </p>
    );
  function card(c: Card) {
    return (
      <article className="discovery-card" key={c.campaign_id + c.store_id}>
        <h3>{c.title}</h3>
        <p>
          {c.store_name} · approximately {(c.distance_meters / 1000).toFixed(2)}{" "}
          km
        </p>
        <Link to={`/offers/${c.offer_id}?store_id=${c.store_id}`}>
          Read offer terms
        </Link>
        <button
          className="button"
          disabled={claim.isPending || !query.data?.allowance.remaining}
          onClick={() => claim.mutate(c.campaign_id)}
        >
          Claim this coupon
        </button>
      </article>
    );
  }
  return (
    <section className="daily-coupons">
      <h2>Your daily recommendation</h2>
      <p>
        A suggestion, not an automatic claim. Stock and eligibility are checked
        when you claim.
      </p>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      <Feedback error={claim.error} />
      {query.data && !query.isError && (
        <>
          <p>
            {query.data.allowance.remaining} of {query.data.allowance.limit}{" "}
            {query.data.allowance.period.toLowerCase()} claims remaining. Resets{" "}
            {new Date(query.data.allowance.resets_at).toLocaleString()} (device
            time; policy: {query.data.allowance.timezone}).
          </p>
          {query.data.recommendation ? (
            card(query.data.recommendation)
          ) : (
            <p>
              No eligible coupon here today. Try another place or explicitly
              expand the radius; ordinary offers remain below.
            </p>
          )}
          {!query.data.recommendation &&
            maxRadius &&
            radius < maxRadius &&
            onExpand && (
              <button onClick={onExpand}>
                Expand coupon search to {maxRadius} km
              </button>
            )}
          <h3>Stores’ daily picks</h3>
          <div className="discovery-grid">
            {query.data.daily_picks.map(card)}
          </div>
          {!query.data.daily_picks.length && (
            <p>
              No eligible store picks in this area. You can still browse
              ordinary offers.
            </p>
          )}
          <button
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 12))}
          >
            Previous picks
          </button>
          <button
            disabled={query.data.next_offset === null}
            onClick={() => setOffset(query.data!.next_offset!)}
          >
            More picks
          </button>
        </>
      )}
    </section>
  );
}
