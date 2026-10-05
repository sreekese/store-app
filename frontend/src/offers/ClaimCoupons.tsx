import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { authorized, raw } from "../auth/client";
import { Feedback, QueryState } from "../profiles/shared";
import type { Campaign } from "./Campaigns";
interface Allowance {
  period?: string;
  remaining: number;
  used: number;
  limit: number;
  resets_at: string;
  timezone: string;
}
interface Receipt {
  id: string;
  title: string;
  status: string;
  expires_at: string;
}
export default function ClaimCoupons({
  offerId,
  storeId,
}: {
  offerId: string;
  storeId: string;
}) {
  const navigate = useNavigate();
  const auth = useAuth(),
    client = useQueryClient(),
    [offset, setOffset] = useState(0),
    keys = useRef<Record<string, string>>({});
  const list = useQuery({
    queryKey: ["available-campaigns", offerId, storeId, offset],
    queryFn: () =>
      raw<Campaign[]>(
        `/offers/${offerId}/campaigns?store_id=${encodeURIComponent(storeId)}&offset=${offset}`,
      ),
    refetchInterval: 30000,
  });
  const allowance = useQuery({
    queryKey: ["claim-allowance", auth.user?.id],
    queryFn: () => authorized<Allowance>("/shopper/allowance"),
    enabled: auth.user?.role === "USER",
    refetchInterval: 30000,
  });
  const claim = useMutation({
    mutationFn: (id: string) => {
      keys.current[id] ||= crypto.randomUUID();
      return authorized<Receipt>(`/shopper/campaigns/${id}/claim`, {
        method: "POST",
        headers: { "Idempotency-Key": keys.current[id] },
      });
    },
    onSuccess: (_receipt, campaignId) => {
      delete keys.current[campaignId];
      void client.invalidateQueries({ queryKey: ["claim-allowance"] });
      void client.invalidateQueries({ queryKey: ["available-campaigns"] });
      void client.invalidateQueries({ queryKey: ["claim-receipts"] });
      void client.invalidateQueries({ queryKey: ["wallet"] });
      navigate(`/app/coupons/${_receipt.id}`);
    },
  });
  if (auth.user && auth.user.role !== "USER") return null;
  return (
    <section>
      <h2>Available coupons</h2>
      <QueryState
        pending={list.isPending}
        error={list.error}
        retry={list.refetch}
      />
      {auth.user && (
        <>
          <QueryState
            pending={allowance.isPending}
            error={allowance.error}
            retry={allowance.refetch}
          />
          {allowance.data && (
            <p>
              {allowance.data.remaining} of {allowance.data.limit}{" "}
              {allowance.data.period?.toLowerCase() || "daily"} claims
              remaining. Resets{" "}
              {new Date(allowance.data.resets_at).toLocaleString()} (shown in
              your device timezone; policy: {allowance.data.timezone}).
            </p>
          )}
        </>
      )}
      <Feedback error={claim.error} />
      {claim.data && (
        <div role="status" className="notice">
          <strong>Coupon claimed: {claim.data.title}</strong>
          <p>Reference: {claim.data.id}</p>
          <p>
            Valid until {new Date(claim.data.expires_at).toLocaleString()}. Your
            claim is saved in your wallet.
          </p>
        </div>
      )}
      {list.data?.length === 0 && (
        <p>
          No claimable coupons at this branch right now. Viewing an offer does
          not reserve a coupon.
        </p>
      )}
      {list.data?.map((c) => (
        <article className="account-panel" key={c.id}>
          <h3>{c.title}</h3>
          <p>
            {c.available_count} coupons left · lifetime limit {c.per_user_limit}{" "}
            per shopper.
          </p>
          <p>
            Valid{" "}
            {c.validity_hours
              ? `for ${c.validity_hours} hours after claim, capped at campaign end`
              : "until campaign end"}
            : {new Date(c.expires_at).toLocaleString()}.
          </p>
          <p>
            Claiming uses one daily allowance. Expiry or cancellation does not
            restore it. Customer eligibility uses successful redemptions on this
            platform.
          </p>
          {auth.user ? (
            <button
              className="button"
              disabled={
                claim.isPending ||
                !allowance.data ||
                allowance.data.remaining === 0
              }
              onClick={() => claim.mutate(c.id)}
            >
              {claim.isPending ? "Claiming…" : "Claim coupon"}
            </button>
          ) : (
            <Link
              className="button"
              to={
                "/login?returnTo=" +
                encodeURIComponent(`/offers/${offerId}?store_id=${storeId}`)
              }
            >
              Sign in to claim
            </Link>
          )}
        </article>
      ))}
      <div className="form-actions">
        <button
          className="text-button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Previous coupons
        </button>
        <button
          className="text-button"
          disabled={!list.data || list.data.length < 25 || offset >= 10000}
          onClick={() => setOffset(offset + 25)}
        >
          More coupons
        </button>
      </div>
    </section>
  );
}
export function ClaimReceipts() {
  const [offset, setOffset] = useState(0),
    query = useQuery({
      queryKey: ["claim-receipts", offset],
      queryFn: () => authorized<Receipt[]>(`/shopper/claims?offset=${offset}`),
    });
  return (
    <section className="account-panel">
      <h2>Saved coupon claims</h2>
      <Link className="button" to="/app/coupons">
        Open my wallet
      </Link>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data?.length === 0 && (
        <p>
          You haven’t claimed a coupon yet. Explore an offer to see its
          available coupons.
        </p>
      )}
      {query.data?.map((c) => (
        <article key={c.id}>
          <h3>{c.title}</h3>
          <p>
            {c.status} · expires {new Date(c.expires_at).toLocaleString()}
          </p>
          <small>Reference: {c.id}</small>
        </article>
      ))}
      <p>
        Your claims are saved in your coupon wallet. Show an active coupon to
        authorized store staff to redeem it.
      </p>
      <div className="form-actions">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Previous claims
        </button>
        <button
          disabled={!query.data || query.data.length < 25 || offset >= 10000}
          onClick={() => setOffset(offset + 25)}
        >
          More claims
        </button>
      </div>
    </section>
  );
}
