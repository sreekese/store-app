import { TrackView } from "../analytics/tracking";
import { ReviewForm } from "../trust/Reviews";
import { ReportForm } from "../trust/Support";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { QueryState } from "../profiles/shared";
import { discountLabel, type OfferFields } from "../offers/types";
interface Receipt {
  id: string;
  title: string;
  status: string;
  expires_at: string;
  claimed_at: string;
}
interface Detail extends Receipt {
  redemption?: {
    id: string;
    store_name: string;
    store_id: string;
    purchase_amount: string;
    discount_amount: string;
    payable_amount: string;
  } | null;
  business_name: string;
  offer: OfferFields;
  eligibility: string;
  branches: {
    id: string;
    name: string;
    address: string;
    city: string;
    timezone: string;
    currently_available: boolean;
    hours: {
      day_of_week: number;
      is_closed: boolean;
      open_time: string | null;
      close_time: string | null;
      closes_next_day: boolean;
    }[];
  }[];
  redeemed_at: string | null;
  claim_token: string | null;
  availability_message: string;
  server_time: string;
}
const states = ["ACTIVE", "REDEEMED", "EXPIRED", "CANCELLED"] as const;
function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="header">
        <Link className="brand" to="/app">
          ✳ nearperk.
        </Link>
        <nav aria-label="Shopper navigation">
          <Link to="/app">Discover</Link>
          <Link to="/app/coupons">My coupons</Link>
          <Link to="/app/support">Support</Link>
        </nav>
      </header>
      <main className="container wallet-shell">{children}</main>
    </>
  );
}
export default function Wallet() {
  const auth = useAuth(),
    [search, setSearch] = useSearchParams();
  const status = states.find((s) => s === search.get("status")) || "ACTIVE";
  const requestedOffset = Number(search.get("offset") || 0);
  const offset =
    Number.isInteger(requestedOffset) &&
    requestedOffset >= 0 &&
    requestedOffset <= 10000
      ? requestedOffset
      : 0;
  const setOffset = (value: number) =>
    setSearch({ status, offset: String(value) });
  const query = useQuery({
    queryKey: ["wallet", auth.user?.id, status, offset],
    queryFn: () =>
      authorized<{ claims: Receipt[]; next_offset: number | null }>(
        `/shopper/wallet?status=${status}&offset=${offset}&limit=12`,
      ),
    retry: false,
    refetchInterval: 30000,
    gcTime: 0,
  });
  return (
    <Shell>
      <p className="eyebrow">YOUR SAVED PERKS</p>
      <h1>My coupons</h1>
      <p>Your claimed coupons, with the terms saved when you claimed them.</p>
      <div className="category-pills" role="group" aria-label="Coupon status">
        {states.map((s) => (
          <button
            key={s}
            aria-pressed={status === s}
            onClick={() => {
              setSearch({ status: s });
            }}
          >
            {s.charAt(0) + s.slice(1).toLowerCase()}
          </button>
        ))}
      </div>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && !query.isError && (
        <>
          {query.data.claims.length === 0 && (
            <div className="notice">
              <p>No {status.toLowerCase()} coupons here yet.</p>
              <Link className="text-button" to="/app">
                Explore nearby offers
              </Link>
            </div>
          )}
          <div className="discovery-grid wallet-grid">
            {query.data.claims.map((c) => (
              <article className="discovery-card" key={c.id}>
                <span className="badge">
                  {c.status === "CLAIMED" ? "Active" : c.status.toLowerCase()}
                </span>
                <h2>{c.title}</h2>
                <p>Expires {new Date(c.expires_at).toLocaleString()}</p>
                <Link className="button" to={`/app/coupons/${c.id}`}>
                  View coupon
                </Link>
              </article>
            ))}
          </div>
          <div className="form-actions">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 12))}
            >
              Previous coupons
            </button>
            <button
              disabled={query.data.next_offset === null}
              onClick={() => setOffset(query.data!.next_offset!)}
            >
              More coupons
            </button>
          </div>
        </>
      )}
    </Shell>
  );
}
export function CouponDetail() {
  const { id } = useParams(),
    auth = useAuth(),
    [visible, setVisible] = useState(!document.hidden),
    [tick, setTick] = useState(0),
    [copied, setCopied] = useState("");
  const query = useQuery({
    queryKey: ["wallet-detail", auth.user?.id, id],
    queryFn: async () => {
      const receivedAt = performance.now();
      return {
        coupon: await authorized<Detail>(`/shopper/wallet/${id}`),
        receivedAt,
      };
    },
    retry: false,
    refetchInterval: 15000,
    gcTime: 0,
  });
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    const change = () => {
      setVisible(!document.hidden);
      if (!document.hidden) void query.refetch();
    };
    document.addEventListener("visibilitychange", change);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", change);
    };
  }, [query.refetch]);
  const data = query.data,
    c = data?.coupon;
  // Advance server time monotonically; a wrong device clock cannot prolong code display.
  const expired =
    !!c &&
    !!data &&
    Date.parse(c.server_time) + performance.now() - data.receivedAt >=
      Date.parse(c.expires_at);
  const usable =
    !!c?.claim_token &&
    c.status === "CLAIMED" &&
    !expired &&
    visible &&
    !query.isError &&
    !query.isFetching;
  async function copy() {
    setCopied("");
    try {
      await navigator.clipboard.writeText(c!.claim_token!);
      setCopied("Code copied. Keep it private.");
    } catch {
      setCopied(
        "Copy is unavailable. Select the manual code below to copy it.",
      );
    }
  }
  return (
    <Shell>
      <Link className="text-button" to="/app/coupons">
        ← My coupons
      </Link>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {c && !query.isError && (
        <article className="account-panel coupon-detail" data-tick={tick}>
          <p className="eyebrow">{c.business_name}</p>
          <TrackView kind="COUPON_VIEWED" id={c.id} />
          <h1>{c.title}</h1>
          <span className="badge">
            {expired && c.status === "CLAIMED" ? "EXPIRED" : c.status}
          </span>
          <p className="coupon-benefit">{discountLabel(c.offer)}</p>
          <p>{c.offer.description}</p>
          <p>Claimed {new Date(c.claimed_at).toLocaleString()}</p>
          <p>
            <strong>Expires {new Date(c.expires_at).toLocaleString()}</strong>
          </p>
          <small>
            Dates shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}.
            Expiry is exclusive.
          </small>
          {usable ? (
            <section className="coupon-code" aria-label="Private coupon code">
              <QRCodeSVG
                value={c.claim_token!}
                size={224}
                level="M"
                marginSize={4}
                title="Private coupon QR code"
              />
              <label>
                Manual coupon code
                <input
                  readOnly
                  value={c.claim_token!}
                  autoComplete="off"
                  spellCheck={false}
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <button className="button" onClick={() => void copy()}>
                Copy code
              </button>
              <p role="status">{copied}</p>
              <p>
                Keep this code private. Share it only with authorized staff when
                using your coupon.
              </p>
            </section>
          ) : (
            <div className="notice">
              {expired && c.status === "CLAIMED"
                ? "This coupon has expired. Its code is no longer available."
                : query.isFetching
                  ? "Refreshing coupon status…"
                  : c.availability_message}
            </div>
          )}
          {usable && <p className="notice">{c.availability_message}</p>}
          {c.redeemed_at && (
            <p>
              Redeemed {new Date(c.redeemed_at).toLocaleString()}. Reference:{" "}
              {c.id}
            </p>
          )}
          {c.redemption && (
            <section className="notice">
              <h2>Redemption receipt</h2>
              <p>
                {c.redemption.store_name} · receipt {c.redemption.id}
              </p>
              <p>Recorded eligible purchase ₹{c.redemption.purchase_amount}</p>
              <p>
                Benefit ₹{c.redemption.discount_amount} · eligible total after
                discount ₹{c.redemption.payable_amount}
              </p>
              <small>
                Amounts were recorded by the store. This is not a payment
                receipt.
              </small>
            </section>
          )}
          <h2>Saved offer terms</h2>
          <p className="offer-terms">{c.offer.terms_conditions}</p>
          <dl className="offer-facts">
            <div>
              <dt>Minimum purchase</dt>
              <dd>₹{c.offer.minimum_purchase}</dd>
            </div>
            {c.offer.maximum_discount && (
              <div>
                <dt>Maximum discount</dt>
                <dd>₹{c.offer.maximum_discount}</dd>
              </div>
            )}
            <div>
              <dt>Offer audience</dt>
              <dd>{c.offer.customer_type.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Eligibility when claimed</dt>
              <dd>{c.eligibility.replaceAll("_", " ")}</dd>
            </div>
          </dl>
          <p>
            Customer eligibility is based on successful redemptions with this
            business on this platform. These terms are preserved from your
            claim.
          </p>
          <h2>Participating branches</h2>
          {c.branches.map((b) => (
            <section className="branch-card" key={b.id}>
              <h3>{b.name}</h3>
              <p>
                {b.address}, {b.city}
              </p>
              <p>
                {b.currently_available
                  ? "Branch is active. Check opening hours before visiting."
                  : "Temporarily unavailable. Check again before visiting."}
              </p>
              <p>Saved opening hours · {b.timezone}</p>
              {b.hours.length ? (
                <ul>
                  {b.hours.map((h) => (
                    <li key={h.day_of_week}>
                      {
                        [
                          "Monday",
                          "Tuesday",
                          "Wednesday",
                          "Thursday",
                          "Friday",
                          "Saturday",
                          "Sunday",
                        ][h.day_of_week]
                      }
                      :{" "}
                      {h.is_closed
                        ? "Closed"
                        : `${h.open_time}–${h.close_time}${h.closes_next_day ? " (next day)" : ""}`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>Opening hours were not supplied when claimed.</p>
              )}
            </section>
          ))}
          {c.status === "REDEEMED" && c.redemption && (
            <ReviewForm key={c.redemption.id} redemptionId={c.redemption.id} />
          )}
          <details>
            <summary>Need help with this coupon?</summary>
            <ReportForm
              key={`${c.id}-${c.redemption?.id || "unredeemed"}`}
              target="CLAIM"
              id={c.id}
              stores={
                c.redemption
                  ? [
                      {
                        id: c.redemption.store_id,
                        name: c.redemption.store_name,
                      },
                    ]
                  : c.branches
              }
            />
            <Link to="/app/support">Track my support cases</Link>
          </details>
        </article>
      )}
    </Shell>
  );
}
