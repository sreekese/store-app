import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { raw } from "../auth/client";
import { Field, QueryState, type Hours } from "../profiles/shared";
import { useDeviceLocation, type Coordinates } from "./useDeviceLocation";
const AdSlot = lazy(() => import("../advertisements/AdSlot"));
const DailyCoupons = lazy(() => import("../daily/DailyCoupons"));
const OfferBrowser = lazy(() => import("../offers/OfferBrowser"));
interface Config {
  default_radius_km: number;
  max_radius_km: number;
}
interface Place extends Coordinates {
  id: string;
  label: string;
  reference_name: string;
}
interface PublicStore extends Coordinates {
  id: string;
  name: string;
  business_name: string;
  category: string;
  address: string;
  city: string;
  area: string;
  state: string;
  country: string;
  postal_code: string;
  phone: string;
  timezone: string;
  hours: Hours[];
  is_open: boolean | null;
  distance_meters: number | null;
}
interface Results {
  centre: { type: "Point"; coordinates: [number, number] };
  radius_km: number;
  stores: PublicStore[];
  next_offset: number | null;
}
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function StoreCard({ store }: { store: PublicStore }) {
  const [expanded, setExpanded] = useState(false);
  const detail = useQuery({
    queryKey: ["public-store", store.id],
    queryFn: () => raw<PublicStore>("/locations/stores/" + store.id),
    enabled: expanded,
    retry: false,
    staleTime: 0,
  });
  const info = detail.data || store;
  return (
    <article className="discovery-card">
      <div className="store-initial" aria-hidden="true">
        {store.name.slice(0, 1)}
      </div>
      <div className="section-heading">
        <span className="eyebrow">{store.category}</span>
        <span className="distance">
          {store.distance_meters == null
            ? ""
            : `${(store.distance_meters / 1000).toFixed(2)} km away`}
        </span>
      </div>
      <h3>{store.name}</h3>
      <p>{store.business_name}</p>
      <p>{[store.area, store.city].filter(Boolean).join(", ")}</p>
      <span className="badge">
        {info.is_open === null
          ? "Hours not provided"
          : info.is_open
            ? "Open now"
            : "Closed now"}
      </span>
      <button
        className="text-button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "Hide details" : `View details: ${store.name}`}
      </button>
      {expanded && (
        <div className="store-details">
          <QueryState
            pending={detail.isPending}
            error={detail.error}
            retry={detail.refetch}
          />
          {detail.data && !detail.isError && (
            <>
              <p>
                {info.address}, {info.city}, {info.state} {info.postal_code},{" "}
                {info.country}
              </p>
              <p>Phone: {info.phone || "Not provided"}</p>
              <p>Store timezone: {info.timezone}</p>
              <p>
                Map point: {info.latitude}, {info.longitude}
              </p>
              {info.hours.length > 0 ? (
                <dl className="weekly-hours">
                  {[...info.hours]
                    .sort((a, b) => a.day_of_week - b.day_of_week)
                    .map((hour) => (
                      <div key={hour.day_of_week}>
                        <dt>{dayNames[hour.day_of_week]}</dt>
                        <dd>
                          {hour.is_closed
                            ? "Closed"
                            : `${hour.open_time}–${hour.close_time}${hour.closes_next_day ? " (next day)" : ""}`}
                        </dd>
                      </div>
                    ))}
                </dl>
              ) : (
                <p>Ask the store about its opening hours.</p>
              )}
            </>
          )}
        </div>
      )}
    </article>
  );
}
export default function Discover() {
  const config = useQuery({
    queryKey: ["discovery-config"],
    queryFn: () => raw<Config>("/locations/config"),
    refetchInterval: 60000,
    retry: false,
  });
  const gps = useDeviceLocation();
  const [placeText, setPlaceText] = useState(""),
    [searchTerm, setSearchTerm] = useState(""),
    [placePage, setPlacePage] = useState(0);
  const [manual, setManual] = useState({ latitude: "", longitude: "" });
  const [centre, setCentre] = useState<
      (Coordinates & { label: string }) | null
    >(null),
    [radius, setRadius] = useState<number | null>(null),
    [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Place | null>(null);
  const places = useQuery({
    queryKey: ["discovery-places", searchTerm, placePage],
    queryFn: () =>
      raw<Place[]>(
        `/locations/places?q=${encodeURIComponent(searchTerm)}&offset=${placePage}`,
      ),
    enabled: searchTerm.length >= 2,
    retry: false,
  });
  const result = useQuery({
    queryKey: [
      "nearby-stores",
      centre?.latitude,
      centre?.longitude,
      radius,
      offset,
    ],
    queryFn: () =>
      raw<Results>(
        `/locations/nearby?latitude=${centre!.latitude}&longitude=${centre!.longitude}&radius_km=${radius}&offset=${offset}&limit=12`,
      ),
    enabled: !!centre && radius !== null,
    retry: false,
  });
  // Browsing position is transient: do not persist precise GPS coordinates in web storage.
  useEffect(() => {
    if (!centre) return;
    const refresh = () => {
      if (document.visibilityState === "visible") void result.refetch();
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [centre, result.refetch]);
  function choose(point: Coordinates, label: string) {
    gps.cancel();
    setCentre({ ...point, label });
    setRadius(config.data!.default_radius_km);
    setOffset(0);
    setSelected(null);
  }
  return (
    <section id="discover" className="discovery">
      <div className="section-heading">
        <div>
          <p className="eyebrow">A little closer to local</p>
          <h2>Find stores near you.</h2>
          <p>
            Verified local businesses, within{" "}
            {config.data?.default_radius_km || 5} km of the place you choose.
          </p>
        </div>
        <button
          className="button"
          disabled={gps.pending || !config.data}
          onClick={() =>
            gps.locate((point) => choose(point, "Your current location"))
          }
        >
          {gps.pending ? "Finding your location…" : "Use my location"}
        </button>
      </div>
      {config.isError && (
        <div className="notice">
          <p role="alert">Unable to load location settings.</p>
          <button className="text-button" onClick={() => void config.refetch()}>
            Retry location settings
          </button>
        </div>
      )}
      {gps.error && (
        <p role="alert" className="form-error">
          {gps.error}
        </p>
      )}
      <div className="location-picker">
        <form
          className="auth-form place-search"
          onSubmit={(e) => {
            e.preventDefault();
            gps.cancel();
            setSelected(null);
            setSearchTerm(placeText.trim());
            setPlacePage(0);
            if (placeText.trim() === searchTerm && placePage === 0)
              void places.refetch();
          }}
        >
          <Field
            label="City or area"
            placeholder="e.g. Kochi or Fort Kochi"
            required
            minLength={2}
            maxLength={100}
            value={placeText}
            onChange={(e) => setPlaceText(e.target.value)}
          />
          <button
            className="button secondary"
            disabled={
              !config.data || placeText.trim().length < 2 || places.isFetching
            }
          >
            Find places
          </button>
        </form>
        <p className="muted">
          Choose a listed store as your city/area reference point. Search
          centres use its coordinates, not an estimated city centre.
        </p>
        {searchTerm && (
          <>
            <QueryState
              pending={places.isPending}
              error={places.error}
              retry={places.refetch}
            />
            {places.data?.length === 0 && (
              <p className="empty-state">
                No listed reference points found. Try another city/area, use
                GPS, or enter map coordinates below.
              </p>
            )}
            <ul className="place-options">
              {places.data?.map((place) => (
                <li key={place.id}>
                  <button
                    className={
                      selected?.id === place.id
                        ? "place-option selected"
                        : "place-option"
                    }
                    aria-pressed={selected?.id === place.id}
                    onClick={() => {
                      gps.cancel();
                      setSelected(place);
                    }}
                  >
                    <strong>{place.label}</strong>
                    <span>
                      Reference: {place.reference_name} ·{" "}
                      {place.latitude.toFixed(5)}, {place.longitude.toFixed(5)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {(placePage > 0 || places.data?.length === 20) && (
              <div className="action-row">
                <button
                  className="text-button"
                  disabled={placePage === 0 || places.isFetching}
                  onClick={() => {
                    setSelected(null);
                    setPlacePage((p) => p - 20);
                  }}
                >
                  Previous places
                </button>
                <button
                  className="text-button"
                  disabled={places.data?.length !== 20 || places.isFetching}
                  onClick={() => {
                    setSelected(null);
                    setPlacePage((p) => p + 20);
                  }}
                >
                  More places
                </button>
              </div>
            )}
          </>
        )}
        {selected && (
          <div className="notice">
            <p>
              Search centre: {selected.reference_name}, {selected.label} (
              {selected.latitude.toFixed(5)}, {selected.longitude.toFixed(5)}).
            </p>
            <button
              className="button"
              disabled={!config.data}
              onClick={() =>
                choose(
                  selected,
                  `${selected.reference_name}, ${selected.label}`,
                )
              }
            >
              Search around this place
            </button>
          </div>
        )}
        <details className="coordinate-picker">
          <summary>Enter map coordinates instead</summary>
          <form
            className="auth-form"
            onSubmit={(e) => {
              e.preventDefault();
              choose(
                {
                  latitude: Number(manual.latitude),
                  longitude: Number(manual.longitude),
                },
                "Your chosen map point",
              );
            }}
          >
            <div className="form-grid">
              <Field
                label="Search latitude"
                type="number"
                required
                step="any"
                min={-90}
                max={90}
                value={manual.latitude}
                onChange={(e) => {
                  gps.cancel();
                  setManual({ ...manual, latitude: e.target.value });
                }}
              />
              <Field
                label="Search longitude"
                type="number"
                required
                step="any"
                min={-180}
                max={180}
                value={manual.longitude}
                onChange={(e) => {
                  gps.cancel();
                  setManual({ ...manual, longitude: e.target.value });
                }}
              />
            </div>
            <button className="button secondary" disabled={!config.data}>
              Search this map point
            </button>
          </form>
        </details>
      </div>
      {centre && (
        <>
          <div className="search-summary">
            <div>
              <strong>{centre.label}</strong>
              <p>
                {centre.latitude.toFixed(5)}, {centre.longitude.toFixed(5)} ·
                Within {radius} km
              </p>
              <small>
                Approximate straight-line distance, not travel distance. Opening
                times use each store’s timezone.
              </small>
            </div>
            <button
              className="text-button"
              disabled={result.isFetching}
              onClick={() => void result.refetch()}
            >
              Refresh stores
            </button>
          </div>
          <QueryState
            pending={result.isPending}
            error={result.error}
            retry={result.refetch}
          />
          {!result.isError && result.data && (
            <>
              {result.data.stores.length === 0 ? (
                <div className="notice">
                  <h3>No stores found in this radius.</h3>
                  <p>Choose another place or try again later.</p>
                  {offset === 0 &&
                    config.data &&
                    radius! < config.data.max_radius_km && (
                      <button
                        className="button secondary"
                        onClick={() => {
                          setRadius(config.data!.max_radius_km);
                          setOffset(0);
                        }}
                      >
                        Expand to {config.data.max_radius_km} km
                      </button>
                    )}
                </div>
              ) : (
                <div className="discovery-grid">
                  {result.data.stores.map((store) => (
                    <StoreCard key={store.id} store={store} />
                  ))}
                </div>
              )}
              <div className="action-row pagination">
                <button
                  className="text-button"
                  disabled={offset === 0 || result.isFetching}
                  onClick={() => setOffset(Math.max(0, offset - 12))}
                >
                  Previous stores
                </button>
                <span>Page {offset / 12 + 1}</span>
                <button
                  className="text-button"
                  disabled={
                    result.data.next_offset === null || result.isFetching
                  }
                  onClick={() => setOffset(result.data!.next_offset!)}
                >
                  Next stores
                </button>
              </div>
            </>
          )}
        </>
      )}
      <Suspense fallback={<p role="status">Loading offers…</p>}>
        {centre && radius !== null && (
          <DailyCoupons
            key={`${centre.latitude}:${centre.longitude}:${radius}`}
            latitude={centre.latitude}
            longitude={centre.longitude}
            maxRadius={config.data?.max_radius_km}
            onExpand={() => {
              if (config.data) {
                setRadius(config.data.max_radius_km);
                setOffset(0);
              }
            }}
            radius={radius}
          />
        )}
        {centre && radius !== null && <AdSlot placement="BELOW_DAILY" />}
        <OfferBrowser
          key={`${centre?.latitude ?? "all"}:${centre?.longitude ?? "all"}:${radius}`}
          centre={centre}
          radius={radius}
        />
        <AdSlot placement="BELOW_OFFERS" />
      </Suspense>
    </section>
  );
}
