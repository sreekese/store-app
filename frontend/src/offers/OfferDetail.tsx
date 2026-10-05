import { TrackView } from "../analytics/tracking";
import Reviews from "../trust/Reviews";
import ClaimCoupons from "./ClaimCoupons";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { raw } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { homePaths } from "../auth/types";
import { QueryState } from "../profiles/shared";
import { discountLabel, type PublicOffer } from "./types";
export default function OfferDetail() {
  const { id } = useParams(),
    [search] = useSearchParams(),
    store = search.get("store_id"),
    auth = useAuth();
  const query = useQuery({
    queryKey: ["offer-detail", id, store],
    queryFn: () =>
      raw<PublicOffer>(
        `/offers/${id}${store ? "?store_id=" + encodeURIComponent(store) : ""}`,
      ),
    retry: false,
    refetchInterval: 60000,
  });
  const offer = query.data;
  return (
    <>
      <header className="header">
        <Link className="brand" to="/">
          ✳ nearperk.
        </Link>
        <nav>
          <Link to="/">Discover</Link>
          <Link
            to={
              auth.user
                ? homePaths[auth.user.role]
                : "/login?returnTo=" +
                  encodeURIComponent(
                    `/offers/${id}${store ? "?store_id=" + store : ""}`,
                  )
            }
          >
            {auth.user ? "My account" : "Sign in"}
          </Link>
        </nav>
      </header>
      <main className="container offer-detail">
        <Link className="text-button" to="/#discover">
          ← Browse local offers
        </Link>
        <QueryState
          pending={query.isPending}
          error={query.error}
          retry={query.refetch}
        />
        {offer && !query.isError && (
          <article className="account-panel">
            <TrackView kind="OFFER_VIEWED" id={offer.id} />
            {offer.image_url && (
              <img
                className="offer-detail-image"
                src={offer.image_url}
                alt=""
                referrerPolicy="no-referrer"
                onError={(e) => {
                  e.currentTarget.hidden = true;
                }}
              />
            )}
            <p className="eyebrow">
              {offer.category_name} · {offer.business_name}
            </p>
            <h1>{offer.title}</h1>
            <span className="badge">{discountLabel(offer)}</span>
            <p>{offer.description}</p>
            <h2>Where to visit</h2>
            <p>
              {offer.store_name},{" "}
              {[offer.area, offer.city].filter(Boolean).join(", ")}
            </p>
            <p>
              {offer.store_id
                ? "Valid at this branch."
                : "Available at eligible branches of this business. This is the selected branch."}
            </p>
            <h2>Know before you go</h2>
            <dl className="offer-facts">
              <div>
                <dt>Minimum purchase</dt>
                <dd>₹{offer.minimum_purchase}</dd>
              </div>
              {offer.maximum_discount && (
                <div>
                  <dt>Maximum discount</dt>
                  <dd>₹{offer.maximum_discount}</dd>
                </div>
              )}
              <div>
                <dt>Customer audience</dt>
                <dd>{offer.customer_type.replaceAll("_", " ")}</dd>
              </div>
              <div>
                <dt>Starts</dt>
                <dd>{new Date(offer.starts_at).toLocaleString()}</dd>
              </div>
              <div>
                <dt>Ends</dt>
                <dd>{new Date(offer.expires_at).toLocaleString()}</dd>
              </div>
            </dl>
            <small>
              Dates are shown in your device timezone:{" "}
              {Intl.DateTimeFormat().resolvedOptions().timeZone}.
            </small>
            <h2>Offer terms</h2>
            <p className="offer-terms">{offer.terms_conditions}</p>
            <ClaimCoupons offerId={offer.id} storeId={offer.matched_store_id} />
            <Reviews
              key={`${offer.id}-${offer.matched_store_id}`}
              offerId={offer.id}
              storeId={offer.matched_store_id}
            />
            {auth.user?.role === "USER" && (
              <p>
                <Link
                  to={`/app/support?target=OFFER&id=${offer.id}&store=${offer.matched_store_id}`}
                >
                  Report this offer
                </Link>
                {" · "}
                <Link
                  to={`/app/support?target=STORE&id=${offer.matched_store_id}&store=${offer.matched_store_id}`}
                >
                  Report this store
                </Link>
              </p>
            )}
          </article>
        )}
      </main>
    </>
  );
}
