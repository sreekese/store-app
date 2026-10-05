import { TrackView } from "../analytics/tracking";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { raw } from "../auth/client";
import { QueryState, type Hours } from "../profiles/shared";
import OfferBrowser from "../offers/OfferBrowser";
interface Store {
  id: string;
  name: string;
  business_name: string;
  address: string;
  city: string;
  state: string;
  postal_code: string;
  phone: string;
  timezone: string;
  is_open: boolean | null;
  hours: Hours[];
}
export default function StoreDetail() {
  const { id } = useParams();
  const query = useQuery({
    queryKey: ["store-destination", id],
    queryFn: () => raw<Store>(`/locations/stores/${id}`),
    retry: false,
    refetchInterval: 30000,
  });
  const store = query.data;
  return (
    <>
      <header className="header">
        <Link className="brand" to="/">
          ✳ nearperk.
        </Link>
        <nav>
          <Link to="/">Discover</Link>
          <Link to="/app/coupons">My coupons</Link>
        </nav>
      </header>
      <main className="container workspace-shell">
        <QueryState
          pending={query.isPending}
          error={query.error}
          retry={query.refetch}
        />
        {store && !query.isError && (
          <>
            <section className="account-panel">
              <TrackView kind="STORE_VIEWED" id={store.id} />
              <p className="eyebrow">{store.business_name}</p>
              <h1>{store.name}</h1>
              <span className="badge">
                {store.is_open === null
                  ? "Hours not provided"
                  : store.is_open
                    ? "Open now"
                    : "Closed now"}
              </span>
              <p>
                {store.address}, {store.city}, {store.state} {store.postal_code}
              </p>
              <p>Phone: {store.phone || "Not provided"}</p>
              <h2>Opening hours</h2>
              <p>{store.timezone}</p>
              {store.hours.length ? (
                <ul>
                  {store.hours.map((h) => (
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
                <p>Ask the store about its opening hours.</p>
              )}
            </section>
            <OfferBrowser
              key={store.id}
              centre={null}
              radius={null}
              storeId={store.id}
            />
          </>
        )}
      </main>
    </>
  );
}
