import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { raw } from "../auth/client";
import { Field, QueryState } from "../profiles/shared";
import { discountLabel, type Category, type PublicOffer } from "./types";
interface Page {
  offers: PublicOffer[];
  next_offset: number | null;
  radius_km: number | null;
}
export default function OfferBrowser({
  centre,
  radius,
  storeId,
}: {
  centre: { latitude: number; longitude: number; label: string } | null;
  radius: number | null;
  storeId?: string;
}) {
  const [category, setCategory] = useState(""),
    [text, setText] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0);
  const categories = useQuery({
    queryKey: ["offer-categories"],
    queryFn: () => raw<Category[]>("/categories"),
    retry: false,
  });
  const query = useQuery({
    queryKey: [
      "public-offers",
      storeId,
      centre?.latitude,
      centre?.longitude,
      radius,
      category,
      search,
      offset,
    ],
    queryFn: () => {
      const params = new URLSearchParams({
        offset: String(offset),
        limit: "12",
      });
      if (centre && radius !== null) {
        params.set("latitude", String(centre.latitude));
        params.set("longitude", String(centre.longitude));
        params.set("radius_km", String(radius));
      }
      if (storeId) params.set("store_id", storeId);
      if (category) params.set("category_id", category);
      if (search) params.set("q", search);
      return raw<Page>("/offers?" + params.toString());
    },
    retry: false,
    refetchInterval: 60000,
  });
  return (
    <section className="offer-marketplace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">A little more rewarding</p>
          <h2>
            {storeId
              ? "Offers at this branch"
              : centre
                ? "Offers around this place"
                : "Explore local offers"}
          </h2>
          <p>
            {storeId
              ? "Current offers for this branch. Open an offer to read its terms and check coupon availability."
              : centre
                ? `Within ${radius} km of ${centre.label}. Approximate straight-line distance.`
                : "Browsing all listed locations. Choose a location above to see nearby offers."}
          </p>
        </div>
        <button
          className="text-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Refresh offers
        </button>
      </div>
      <QueryState
        pending={categories.isPending}
        error={categories.error}
        retry={categories.refetch}
      />
      <div
        className="category-pills"
        role="group"
        aria-label="Browse offer categories"
      >
        <button
          aria-pressed={!category}
          onClick={() => {
            setCategory("");
            setOffset(0);
          }}
        >
          All categories
        </button>
        {categories.data?.map((item) => (
          <button
            key={item.id}
            aria-pressed={category === item.id}
            onClick={() => {
              setCategory(item.id);
              setOffset(0);
            }}
          >
            {item.name}
          </button>
        ))}
      </div>
      <form
        className="auth-form place-search"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(text.trim());
          setOffset(0);
          if (search === text.trim() && offset === 0) void query.refetch();
        }}
      >
        <Field
          label="Search offers"
          maxLength={100}
          placeholder="Search offers or businesses"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="button secondary" disabled={query.isFetching}>
          Find offers
        </button>
      </form>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {!query.isError && query.data && (
        <>
          {query.data.offers.length === 0 ? (
            <div className="notice">
              <h3>No matching offers right now.</h3>
              <p>
                Try another category, search, or location. Offers may be paused,
                expired, or awaiting approval.
              </p>
            </div>
          ) : (
            <div className="discovery-grid offer-grid">
              {query.data.offers.map((offer) => (
                <article className="discovery-card" key={offer.id}>
                  {offer.image_url ? (
                    <img
                      className="offer-image"
                      src={offer.image_url}
                      alt=""
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      onError={(e) => {
                        e.currentTarget.hidden = true;
                      }}
                    />
                  ) : (
                    <div className="offer-ticket" aria-hidden="true">
                      ✳
                    </div>
                  )}
                  <div className="section-heading">
                    <span className="badge">{discountLabel(offer)}</span>
                    <span className="distance">
                      {offer.distance_meters === null
                        ? offer.city
                        : `${(offer.distance_meters / 1000).toFixed(2)} km away`}
                    </span>
                  </div>
                  <h3>{offer.title}</h3>
                  <p>
                    {offer.business_name} · {offer.store_name}
                  </p>
                  <p>
                    {offer.category_name} · {offer.city}
                  </p>
                  <p>
                    For {offer.customer_type.replaceAll("_", " ").toLowerCase()}
                  </p>
                  <p>Ends {new Date(offer.expires_at).toLocaleString()}</p>
                  <Link
                    className="text-button"
                    to={`/offers/${offer.id}?store_id=${offer.matched_store_id}`}
                  >
                    View offer details
                  </Link>
                </article>
              ))}
            </div>
          )}
          <div className="action-row">
            <button
              className="text-button"
              disabled={offset === 0 || query.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 12))}
            >
              Previous offer results
            </button>
            <span>Page {offset / 12 + 1}</span>
            <button
              className="text-button"
              disabled={query.data.next_offset === null || query.isFetching}
              onClick={() => setOffset(query.data!.next_offset!)}
            >
              Next offer results
            </button>
          </div>
        </>
      )}
    </section>
  );
}
