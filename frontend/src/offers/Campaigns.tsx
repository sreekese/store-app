import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import {
  Field,
  Feedback,
  mutate,
  QueryState,
  type Store,
} from "../profiles/shared";
import { localDate, type Offer } from "./types";

export interface Campaign {
  id: string;
  offer_id: string;
  title: string;
  store_ids: string[];
  total_quantity: number;
  claimed_count: number;
  available_count: number;
  per_user_limit: number;
  validity_hours: number | null;
  starts_at: string;
  expires_at: string;
  status: string;
  revision: number;
}
function CampaignForm({
  existing,
  offers,
  stores,
  done,
}: {
  existing: Campaign | null;
  offers: Offer[];
  stores: Store[];
  done: () => void;
}) {
  const [offerId, setOffer] = useState(existing?.offer_id || ""),
    [ids, setIds] = useState<string[]>(existing?.store_ids || []),
    [quantity, setQuantity] = useState(existing?.total_quantity || 100),
    [limit, setLimit] = useState(existing?.per_user_limit || 1),
    [hours, setHours] = useState(existing?.validity_hours?.toString() || ""),
    [start, setStart] = useState(existing ? localDate(existing.starts_at) : ""),
    [end, setEnd] = useState(existing ? localDate(existing.expires_at) : "");
  const client = useQueryClient(),
    locked = !!existing?.claimed_count;
  const selected = offers.find((o) => o.id === offerId);
  const save = useMutation({
    mutationFn: () =>
      mutate<Campaign>(
        existing ? `/merchant/campaigns/${existing.id}` : "/merchant/campaigns",
        {
          offer_id: offerId,
          store_ids: ids,
          total_quantity: quantity,
          per_user_limit: limit,
          validity_hours: hours ? Number(hours) : null,
          starts_at: locked
            ? existing!.starts_at
            : start ===
                localDate(
                  existing?.starts_at ||
                    selected?.starts_at ||
                    new Date().toISOString(),
                )
              ? existing?.starts_at || selected!.starts_at
              : new Date(start).toISOString(),
          expires_at: locked
            ? existing!.expires_at
            : end ===
                localDate(
                  existing?.expires_at ||
                    selected?.expires_at ||
                    new Date().toISOString(),
                )
              ? existing?.expires_at || selected!.expires_at
              : new Date(end).toISOString(),
          ...(existing ? { revision: existing.revision } : {}),
        },
        existing ? "PUT" : "POST",
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["campaigns"] });
      done();
    },
  });
  return (
    <form
      className="profile-form"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h3>{existing ? "Edit campaign" : "New coupon campaign"}</h3>
      <p>
        Select explicit participating branches. Campaign dates must fit within
        the offer period. After the first claim, only quantity can change.
      </p>
      <label>
        Offer
        <select
          required
          disabled={!!existing}
          value={offerId}
          onChange={(e) => {
            const o = offers.find((o) => o.id === e.target.value);
            setOffer(e.target.value);
            setIds([]);
            if (o) {
              setStart(localDate(o.starts_at));
              setEnd(localDate(o.expires_at));
            }
          }}
        >
          <option value="">Choose an offer</option>
          {offers.map((o) => (
            <option value={o.id} key={o.id}>
              {o.title}
            </option>
          ))}
          {existing && !selected && (
            <option value={existing.offer_id}>{existing.title}</option>
          )}
        </select>
      </label>
      <fieldset disabled={locked}>
        <legend>Participating branches</legend>
        {stores
          .filter(
            (s) =>
              s.status === "ACTIVE" &&
              (!selected?.store_id || s.id === selected.store_id),
          )
          .map((s) => (
            <label key={s.id}>
              <input
                type="checkbox"
                checked={ids.includes(s.id)}
                onChange={(e) =>
                  setIds(
                    e.target.checked
                      ? [...ids, s.id]
                      : ids.filter((id) => id !== s.id),
                  )
                }
              />
              {s.name}
            </label>
          ))}
      </fieldset>
      <Field
        label="Total coupons"
        type="number"
        required
        min={Math.max(1, existing?.claimed_count || 0)}
        max={1000000}
        value={quantity}
        onChange={(e) => setQuantity(Number(e.target.value))}
      />
      <Field
        label="Lifetime limit per shopper"
        type="number"
        required
        min={1}
        max={100}
        disabled={locked}
        value={limit}
        onChange={(e) => setLimit(Number(e.target.value))}
      />
      <Field
        label="Valid for hours after claim (blank means campaign end)"
        type="number"
        min={1}
        max={8760}
        disabled={locked}
        value={hours}
        onChange={(e) => setHours(e.target.value)}
      />
      <Field
        label="Campaign starts"
        type="datetime-local"
        required
        disabled={locked}
        value={start}
        onChange={(e) => setStart(e.target.value)}
      />
      <Field
        label="Campaign ends"
        type="datetime-local"
        required
        disabled={locked}
        value={end}
        onChange={(e) => setEnd(e.target.value)}
      />
      <p>
        Dates use your device timezone. Claim validity is capped at campaign
        end. One platform claim per day still applies.
      </p>
      <Feedback error={save.error} />
      <div className="form-actions">
        <button
          className="button"
          disabled={save.isPending || ids.length === 0}
        >
          {save.isPending ? "Saving…" : "Save campaign"}
        </button>
        <button type="button" className="text-button" onClick={done}>
          Cancel editing
        </button>
      </div>
    </form>
  );
}
export default function Campaigns({ admin = false }: { admin?: boolean }) {
  const [offset, setOffset] = useState(0),
    [offerOffset, setOfferOffset] = useState(0),
    [editing, setEditing] = useState<Campaign | null | undefined>(undefined),
    client = useQueryClient();
  const list = useQuery({
    queryKey: ["campaigns", admin, offset],
    queryFn: () =>
      authorized<Campaign[]>(
        `/${admin ? "admin" : "merchant"}/campaigns?offset=${offset}`,
      ),
  });
  const offers = useQuery({
    queryKey: ["campaign-offers", offerOffset],
    queryFn: () =>
      authorized<Offer[]>(`/merchant/offers?offset=${offerOffset}`),
    enabled: !admin && editing !== undefined,
  });
  const stores = useQuery({
    queryKey: ["merchant-stores"],
    queryFn: () => authorized<Store[]>("/merchant/stores"),
    enabled: !admin && editing !== undefined,
  });
  const change = useMutation({
    mutationFn: ({ c, action }: { c: Campaign; action: string }) =>
      mutate<Campaign>(
        `/merchant/campaigns/${c.id}/actions`,
        { revision: c.revision, action },
        "POST",
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["campaigns"] }),
  });
  return (
    <section className="account-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">COUPON INVENTORY</p>
          <h2>{admin ? "Campaign oversight" : "Coupon campaigns"}</h2>
          <button
            className="text-button"
            disabled={list.isFetching}
            onClick={() => {
              setEditing(undefined);
              void list.refetch();
            }}
          >
            Reload campaigns
          </button>
        </div>
        {!admin && (
          <button className="button" onClick={() => setEditing(null)}>
            Create campaign
          </button>
        )}
      </div>
      <p>
        {admin
          ? "Review campaign distribution. Offer moderation and business suspension also stop new claims."
          : "Manage coupon stock and participating branches. Pausing or cancelling distribution preserves existing claims."}
      </p>
      <QueryState
        pending={list.isPending}
        error={list.error}
        retry={list.refetch}
      />
      <Feedback error={change.error} />
      {editing !== undefined && (
        <>
          <QueryState
            pending={offers.isPending || stores.isPending}
            error={offers.error || stores.error}
            retry={() => {
              void offers.refetch();
              void stores.refetch();
            }}
          />
          {offers.data && stores.data && (
            <>
              <CampaignForm
                key={editing?.id || "new"}
                existing={editing}
                offers={offers.data}
                stores={stores.data}
                done={() => setEditing(undefined)}
              />
              <div className="form-actions">
                <button
                  className="text-button"
                  disabled={offerOffset === 0}
                  onClick={() => setOfferOffset(Math.max(0, offerOffset - 25))}
                >
                  Previous offers
                </button>
                <button
                  className="text-button"
                  disabled={offers.data.length < 25}
                  onClick={() => setOfferOffset(offerOffset + 25)}
                >
                  More offers
                </button>
              </div>
            </>
          )}
        </>
      )}
      {list.data?.length === 0 && <p>No coupon campaigns yet.</p>}
      <div className="offer-grid">
        {list.data?.map((c) => (
          <article className="offer-card" key={c.id}>
            <h3>{c.title}</h3>
            <span className="badge">{c.status.replaceAll("_", " ")}</span>
            <p>
              {c.available_count} available · {c.claimed_count} claimed ·{" "}
              {c.total_quantity} total
            </p>
            <p>
              {c.per_user_limit} per shopper · {c.store_ids.length}{" "}
              participating branches
            </p>
            <p>Ends {new Date(c.expires_at).toLocaleString()}</p>
            {!admin && c.status !== "CANCELLED" && (
              <div className="form-actions">
                <button className="text-button" onClick={() => setEditing(c)}>
                  Edit campaign
                </button>
                {["DRAFT", "PAUSED"].includes(c.status) && (
                  <button
                    disabled={change.isPending}
                    onClick={() => change.mutate({ c, action: "ACTIVATE" })}
                  >
                    Activate campaign
                  </button>
                )}
                {["ACTIVE", "SOLD_OUT"].includes(c.status) && (
                  <button
                    disabled={change.isPending}
                    onClick={() => change.mutate({ c, action: "PAUSE" })}
                  >
                    Pause campaign
                  </button>
                )}
                <button
                  disabled={change.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        "Stop new claims permanently? Existing claims remain valid.",
                      )
                    )
                      change.mutate({ c, action: "CANCEL" });
                  }}
                >
                  Cancel distribution
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
      <div className="form-actions">
        <button
          className="text-button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Previous campaigns
        </button>
        <button
          className="text-button"
          disabled={!list.data || list.data.length < 25 || offset >= 10000}
          onClick={() => setOffset(offset + 25)}
        >
          More campaigns
        </button>
      </div>
    </section>
  );
}
