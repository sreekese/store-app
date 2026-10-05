import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { Feedback, QueryState } from "../profiles/shared";
import { AdCard } from "./AdSlot";
import {
  placements,
  type Ad,
  type AdFields,
  type Card,
  type Page,
  type Placement,
} from "./types";
interface Choice {
  id: string;
  label: string;
  starts_at?: string;
  expires_at?: string;
}
interface Preview {
  card: Card;
  preview_token: string;
  destination_available_now: boolean;
  overlap: boolean;
}
function fields(row?: Ad): AdFields {
  return {
    sponsor: row?.sponsor || "",
    headline: row?.headline || "",
    body: row?.body || "",
    image_url: row?.image_url || "",
    image_alt: row?.image_alt || "",
    cta: row?.cta || "Explore",
    placement: row?.placement || "BELOW_OFFERS",
    destination_type: row?.destination_type || "DISCOVER",
    store_id: row?.store_id || null,
    offer_id: row?.offer_id || null,
    starts_at: row?.starts_at || new Date().toISOString(),
    expires_at:
      row?.expires_at || new Date(Date.now() + 86400000).toISOString(),
  };
}
function localDate(value: string) {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function Pages({
  offset,
  next,
  change,
}: {
  offset: number;
  next: number | null;
  change: (n: number) => void;
}) {
  return (
    <div className="action-row">
      <button
        type="button"
        disabled={!offset}
        onClick={() => change(Math.max(0, offset - 20))}
      >
        Previous ads
      </button>
      <button
        type="button"
        disabled={next === null}
        onClick={() => next !== null && change(next)}
      >
        More ads
      </button>
    </div>
  );
}
function Editor({
  row,
  onSaved,
  onCancel,
}: {
  row?: Ad;
  onSaved: (row: Ad) => void;
  onCancel: () => void;
}) {
  const [initial] = useState(() => fields(row)),
    [data, setData] = useState(initial),
    [preview, setPreview] = useState<Preview | null>(null),
    [search, setSearch] = useState(""),
    [term, setTerm] = useState(""),
    [storeOffset, setStoreOffset] = useState(0),
    [offerOffset, setOfferOffset] = useState(0),
    [showHistory, setShowHistory] = useState(false);
  const dirty = JSON.stringify(data) !== JSON.stringify(initial),
    archived = row?.status === "ARCHIVED";
  const stores = useQuery({
    queryKey: ["ad-store-choices", term, storeOffset],
    queryFn: () =>
      authorized<Choice[]>(
        `/advertisements/destinations/stores?q=${encodeURIComponent(term)}&offset=${storeOffset}`,
      ),
    enabled: data.destination_type !== "DISCOVER",
    retry: false,
    gcTime: 0,
  });
  const offers = useQuery({
    queryKey: ["ad-offer-choices", data.store_id, offerOffset],
    queryFn: () =>
      authorized<Choice[]>(
        `/advertisements/destinations/offers?store_id=${data.store_id}&offset=${offerOffset}`,
      ),
    enabled: data.destination_type === "OFFER" && !!data.store_id,
    retry: false,
    gcTime: 0,
  });
  function change(patch: Partial<AdFields>) {
    setData({ ...data, ...patch });
    setPreview(null);
  }
  const save = useMutation({
    mutationFn: () =>
      authorized<Ad>(
        row ? `/advertisements/manage/${row.id}` : "/advertisements/manage",
        {
          method: row ? "PUT" : "POST",
          body: JSON.stringify({
            ...data,
            ...(row ? { revision: row.revision } : {}),
          }),
        },
      ),
    onSuccess: onSaved,
  });
  const loadPreview = useMutation({
    mutationFn: () =>
      authorized<Preview>(`/advertisements/manage/${row!.id}/preview`, {
        method: "POST",
        body: JSON.stringify({ revision: row!.revision }),
      }),
    onSuccess: setPreview,
  });
  const action = useMutation({
    mutationFn: (value: string) =>
      authorized<Ad>(`/advertisements/manage/${row!.id}/actions`, {
        method: "POST",
        body: JSON.stringify({
          revision: row!.revision,
          action: value,
          ...(value === "ENABLE"
            ? { preview_token: preview?.preview_token }
            : {}),
        }),
      }),
    onSuccess: onSaved,
  });
  const reload = useMutation({
    mutationFn: () => authorized<Ad>(`/advertisements/manage/${row!.id}`),
    onSuccess: onSaved,
  });
  const busy =
    save.isPending ||
    loadPreview.isPending ||
    action.isPending ||
    reload.isPending;
  return (
    <section className="account-panel">
      <h2>{row ? "Edit advertisement" : "Create advertisement"}</h2>
      {row && (
        <p>
          Saved state: {row.status} · revision {row.revision}
        </p>
      )}
      <p>
        Saving edits returns an enabled ad to draft and removes it from shoppers
        until you preview and enable the new revision.
      </p>
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <fieldset disabled={busy || archived} className="ad-fields">
          <label>
            Sponsor
            <input
              required
              minLength={2}
              maxLength={150}
              value={data.sponsor}
              onChange={(e) => change({ sponsor: e.target.value })}
            />
          </label>
          <label>
            Headline
            <input
              required
              minLength={3}
              maxLength={120}
              value={data.headline}
              onChange={(e) => change({ headline: e.target.value })}
            />
          </label>
          <label>
            Supporting text
            <textarea
              required
              minLength={3}
              maxLength={500}
              value={data.body}
              onChange={(e) => change({ body: e.target.value })}
            />
          </label>
          <div className="form-grid">
            <label>
              Creative image URL (optional)
              <input
                type="url"
                maxLength={2048}
                value={data.image_url}
                onChange={(e) => change({ image_url: e.target.value })}
              />
            </label>
            <label>
              Image alternative text
              <input
                required={!!data.image_url}
                maxLength={150}
                value={data.image_alt}
                onChange={(e) => change({ image_alt: e.target.value })}
              />
            </label>
          </div>
          <p>
            Use a credential-free HTTPS image URL, or leave it blank for a text
            ad.
          </p>
          <label>
            Call to action
            <input
              required
              minLength={2}
              maxLength={60}
              value={data.cta}
              onChange={(e) => change({ cta: e.target.value })}
            />
          </label>
          <label>
            Placement
            <select
              value={data.placement}
              onChange={(e) =>
                change({ placement: e.target.value as Placement })
              }
            >
              {Object.entries(placements).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Destination
            <select
              value={data.destination_type}
              onChange={(e) => {
                change({
                  destination_type: e.target
                    .value as AdFields["destination_type"],
                  store_id: null,
                  offer_id: null,
                });
                setStoreOffset(0);
                setOfferOffset(0);
              }}
            >
              <option value="DISCOVER">Discovery page</option>
              <option value="STORE">Store page</option>
              <option value="OFFER">Offer at a branch</option>
            </select>
          </label>
          {data.destination_type !== "DISCOVER" && (
            <>
              <label>
                Find a branch
                <input
                  maxLength={100}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <button
                type="button"
                onClick={() => {
                  setTerm(search.trim());
                  setStoreOffset(0);
                }}
              >
                Search branches
              </button>
              {stores.isPending && <p role="status">Loading branches…</p>}
              {stores.isError && <p role="alert">{stores.error.message}</p>}
              <label>
                Branch
                <select
                  required
                  value={data.store_id || ""}
                  onChange={(e) => {
                    change({
                      store_id: e.target.value || null,
                      offer_id: null,
                    });
                    setOfferOffset(0);
                  }}
                >
                  <option value="">Choose an eligible branch</option>
                  {data.store_id &&
                    !stores.data?.some((s) => s.id === data.store_id) && (
                      <option value={data.store_id}>
                        Saved branch (search to change)
                      </option>
                    )}
                  {!stores.isError &&
                    stores.data?.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                </select>
              </label>
              <div className="action-row">
                <button
                  type="button"
                  disabled={!storeOffset}
                  onClick={() => setStoreOffset(storeOffset - 25)}
                >
                  Previous branches
                </button>
                <button
                  type="button"
                  disabled={stores.data?.length !== 25 || storeOffset >= 10000}
                  onClick={() => setStoreOffset(storeOffset + 25)}
                >
                  More branches
                </button>
                <button type="button" onClick={() => void stores.refetch()}>
                  Refresh branches
                </button>
              </div>
            </>
          )}
          {data.destination_type === "OFFER" && data.store_id && (
            <>
              {offers.isError && <p role="alert">{offers.error.message}</p>}
              <label>
                Offer
                <select
                  required
                  value={data.offer_id || ""}
                  onChange={(e) => change({ offer_id: e.target.value || null })}
                >
                  <option value="">Choose an approved offer</option>
                  {data.offer_id &&
                    !offers.data?.some((o) => o.id === data.offer_id) && (
                      <option value={data.offer_id}>
                        Saved offer (choose a current offer if unavailable)
                      </option>
                    )}
                  {!offers.isError &&
                    offers.data?.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label} · {new Date(o.starts_at!).toLocaleString()} –{" "}
                        {new Date(o.expires_at!).toLocaleString()}
                      </option>
                    ))}
                </select>
              </label>
              <p>
                The advertisement schedule must fit within the selected offer's
                dates.
              </p>
              <div className="action-row">
                <button
                  type="button"
                  disabled={!offerOffset}
                  onClick={() => setOfferOffset(offerOffset - 25)}
                >
                  Previous offers
                </button>
                <button
                  type="button"
                  disabled={offers.data?.length !== 25 || offerOffset >= 10000}
                  onClick={() => setOfferOffset(offerOffset + 25)}
                >
                  More offers
                </button>
                <button type="button" onClick={() => void offers.refetch()}>
                  Refresh offers
                </button>
              </div>
            </>
          )}
          <div className="form-grid">
            <label>
              Starts
              <input
                type="datetime-local"
                required
                value={localDate(data.starts_at)}
                onChange={(e) =>
                  change({
                    starts_at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : "",
                  })
                }
              />
            </label>
            <label>
              Ends
              <input
                type="datetime-local"
                required
                value={localDate(data.expires_at)}
                onChange={(e) =>
                  change({
                    expires_at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : "",
                  })
                }
              />
            </label>
          </div>
          <p>
            Times use {Intl.DateTimeFormat().resolvedOptions().timeZone}. Start
            is inclusive; end is exclusive.
          </p>
          <button className="button" disabled={busy || archived}>
            {row ? "Save as draft" : "Create draft"}
          </button>
        </fieldset>
        <Feedback error={save.error} />
      </form>
      {row && (
        <>
          <div className="action-row">
            <button
              disabled={busy || dirty}
              onClick={() => loadPreview.mutate()}
            >
              Preview saved ad
            </button>
            <button disabled={busy} onClick={() => reload.mutate()}>
              Reload saved ad
            </button>
            {row.status === "ENABLED" && (
              <button disabled={busy} onClick={() => action.mutate("DISABLE")}>
                Disable advertisement
              </button>
            )}
            {row.status !== "ARCHIVED" && (
              <button disabled={busy} onClick={() => action.mutate("ARCHIVE")}>
                Archive advertisement
              </button>
            )}
          </div>
          {dirty && <p>Save your changes before previewing or enabling.</p>}
          <Feedback error={loadPreview.error || action.error || reload.error} />
          {preview && !dirty && (
            <section className="ad-preview" aria-label="Shopper preview">
              <h3>Shopper preview</h3>
              <AdCard ad={preview.card} preview />
              <p>Destination: {preview.card.href}</p>
              {!preview.destination_available_now && (
                <p>
                  This destination is not currently visible. A scheduled offer
                  may become visible at its start time; unavailable destinations
                  are hidden from shoppers.
                </p>
              )}
              {preview.overlap && (
                <p role="alert">
                  Another enabled ad overlaps this placement and schedule.
                  Change the dates or disable that ad first.
                </p>
              )}
              <p>
                Publication rechecks destination eligibility and schedule
                conflicts. Preview approval expires after ten minutes.
              </p>
              {row.status !== "ENABLED" && !archived && (
                <button
                  className="button"
                  disabled={busy || preview.overlap}
                  onClick={() => action.mutate("ENABLE")}
                >
                  Enable advertisement
                </button>
              )}
            </section>
          )}
          <details onToggle={(e) => setShowHistory(e.currentTarget.open)}>
            <summary>Advertisement history</summary>
            {showHistory && <History id={row.id} />}
          </details>
        </>
      )}
      <button className="text-button" onClick={onCancel}>
        Close editor
      </button>
    </section>
  );
}
interface Event {
  id: string;
  action: string;
  actor: string;
  created_at: string;
  snapshot: Ad;
}
function History({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const q = useQuery({
    queryKey: ["ad-history", id, offset],
    queryFn: () =>
      authorized<Page<Event>>(
        `/advertisements/manage/${id}/history?offset=${offset}`,
      ),
    retry: false,
    gcTime: 0,
  });
  return (
    <>
      <QueryState pending={q.isPending} error={q.error} retry={q.refetch} />
      {q.data && !q.isError && (
        <>
          {q.data.items.map((e) => (
            <article className="notification-item" key={e.id}>
              <strong>
                {e.action.replaceAll("_", " ")} · {e.actor}
              </strong>
              <p>
                {new Date(e.created_at).toLocaleString()} · revision{" "}
                {e.snapshot.revision} · {e.snapshot.status}
              </p>
              <details>
                <summary>Recorded configuration</summary>
                <p>
                  {e.snapshot.sponsor} · {e.snapshot.headline}
                </p>
                <p>{e.snapshot.body}</p>
                <p>
                  {placements[e.snapshot.placement]} ·{" "}
                  {e.snapshot.destination_type}
                </p>
                <p>{e.snapshot.cta}</p>
                <p>
                  {new Date(e.snapshot.starts_at).toLocaleString()} –{" "}
                  {new Date(e.snapshot.expires_at).toLocaleString()}
                </p>
              </details>
            </article>
          ))}
          <Pages offset={offset} next={q.data.next_offset} change={setOffset} />
        </>
      )}
    </>
  );
}
export default function AdManager() {
  const auth = useAuth(),
    client = useQueryClient(),
    [offset, setOffset] = useState(0),
    [status, setStatus] = useState(""),
    [editing, setEditing] = useState<Ad | null | undefined>(undefined),
    [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["ad-management", auth.user?.id, status, offset],
    queryFn: () =>
      authorized<Page<Ad>>(
        `/advertisements/manage?offset=${offset}${status ? `&status=${status}` : ""}`,
      ),
    retry: false,
    gcTime: 0,
  });
  function saved(row: Ad) {
    setEditing(row);
    setNotice(`Advertisement saved as ${row.status}.`);
    void client.invalidateQueries({ queryKey: ["ad-management"] });
    void client.invalidateQueries({ queryKey: ["ad-history"] });
    void client.invalidateQueries({ queryKey: ["shopper-advertisements"] });
  }
  return (
    <>
      <header className="header">
        <Link className="brand" to="/superadmin/dashboard">
          ✳ nearperk.
        </Link>
        <Link to="/superadmin/dashboard">Back to dashboard</Link>
      </header>
      <main className="container workspace-shell ad-manager">
        <h1>Advertisements</h1>
        <p>
          Manually managed Sponsored placements for shoppers. One enabled ad per
          placement at a time. No billing or automatic coupon claims.
        </p>
        <button
          className="button"
          onClick={() => {
            setEditing(null);
            setNotice("");
          }}
        >
          New advertisement
        </button>
        <Feedback success={notice} />
        {editing !== undefined && (
          <Editor
            key={editing ? `${editing.id}-${editing.revision}` : "new"}
            row={editing || undefined}
            onSaved={saved}
            onCancel={() => setEditing(undefined)}
          />
        )}
        <section className="account-panel">
          <h2>Saved advertisements</h2>
          <label>
            Ad status
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All states</option>
              {["DRAFT", "ENABLED", "DISABLED", "ARCHIVED"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <button
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            Refresh advertisements
          </button>
          <QueryState
            pending={query.isPending}
            error={query.error}
            retry={query.refetch}
          />
          {query.data && !query.isError && (
            <>
              {!query.data.items.length && <p>No advertisements here yet.</p>}
              {query.data.items.map((a) => (
                <article className="notification-item" key={a.id}>
                  <h3>{a.headline}</h3>
                  <p>
                    {a.sponsor} · {placements[a.placement]} · {a.status}
                  </p>
                  <p>
                    {new Date(a.starts_at).toLocaleString()} –{" "}
                    {new Date(a.expires_at).toLocaleString()}
                  </p>
                  <button
                    onClick={() => {
                      setEditing(a);
                      setNotice("");
                    }}
                  >
                    Manage {a.headline}
                  </button>
                </article>
              ))}
              <Pages
                offset={offset}
                next={query.data.next_offset}
                change={setOffset}
              />
            </>
          )}
        </section>
      </main>
    </>
  );
}
