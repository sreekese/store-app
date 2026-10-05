import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized, raw } from "../auth/client";
import {
  Field,
  Feedback,
  mutate,
  QueryState,
  type Merchant,
  type Store,
} from "../profiles/shared";
import {
  discountLabel,
  localDate,
  type Category,
  type Discount,
  type Offer,
  type OfferFields,
} from "./types";
function OfferForm({
  offer,
  categories,
  stores,
  done,
}: {
  offer: Offer | null;
  categories: Category[];
  stores: Store[];
  done: (saved?: boolean) => void;
}) {
  const [form, setForm] = useState<OfferFields>(
    offer
      ? { ...offer }
      : {
          category_id: "",
          store_id: null,
          title: "",
          description: "",
          image_url: "",
          discount_type: "PERCENTAGE",
          discount_value: "20",
          minimum_purchase: "0",
          maximum_discount: null,
          currency: "INR",
          customer_type: "ALL",
          terms_conditions: "",
          starts_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
        },
  );
  const [start, setStart] = useState(localDate(form.starts_at)),
    [end, setEnd] = useState(localDate(form.expires_at)),
    client = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      const payload: OfferFields = {
        category_id: form.category_id,
        store_id: form.store_id,
        title: form.title,
        description: form.description,
        image_url: form.image_url,
        discount_type: form.discount_type,
        discount_value: form.discount_value,
        minimum_purchase: form.minimum_purchase,
        maximum_discount: form.maximum_discount,
        currency: "INR",
        customer_type: form.customer_type,
        terms_conditions: form.terms_conditions,
        starts_at: new Date(start).toISOString(),
        expires_at: new Date(end).toISOString(),
      };
      return mutate<Offer>(
        offer ? `/merchant/offers/${offer.id}` : "/merchant/offers",
        { ...payload, ...(offer ? { revision: offer.revision } : {}) },
        offer ? "PUT" : "POST",
      );
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["merchant-offers"] });
      done(true);
    },
  });
  function discount(type: Discount) {
    setForm({
      ...form,
      discount_type: type,
      discount_value: type === "BOGO" || type === "FREE_ITEM" ? "0" : "20",
      maximum_discount: null,
    });
  }
  return (
    <form
      className="auth-form profile-form offer-form"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h3>{offer ? "Edit offer" : "Create an offer"}</h3>
      <p>
        Saving creates a draft and removes any previous approval. Submit the
        draft when it is ready.
      </p>
      <fieldset disabled={save.isPending}>
        <Field
          label="Offer title"
          required
          minLength={3}
          maxLength={150}
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <label>
          Offer description
          <textarea
            required
            minLength={3}
            maxLength={2000}
            rows={3}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <div className="form-grid">
          <label>
            Offer category
            <select
              required
              value={form.category_id}
              onChange={(e) =>
                setForm({ ...form, category_id: e.target.value })
              }
            >
              <option value="">Choose a category</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Offer branch
            <select
              value={form.store_id || ""}
              onChange={(e) =>
                setForm({ ...form, store_id: e.target.value || null })
              }
            >
              <option value="">All eligible branches</option>
              {stores.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name}
                  {store.status === "INACTIVE" ? " (inactive)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            Discount type
            <select
              value={form.discount_type}
              onChange={(e) => discount(e.target.value as Discount)}
            >
              <option value="PERCENTAGE">Percentage</option>
              <option value="FLAT_AMOUNT">Flat amount (₹)</option>
              <option value="BOGO">Buy one, get one</option>
              <option value="FREE_ITEM">Free item</option>
              <option value="SPECIAL_PRICE">Special price (₹)</option>
            </select>
          </label>
          {!["BOGO", "FREE_ITEM"].includes(form.discount_type) && (
            <Field
              label={
                form.discount_type === "PERCENTAGE"
                  ? "Discount percentage"
                  : "Discount amount / special price (₹)"
              }
              type="number"
              required
              min="0.01"
              max={
                form.discount_type === "PERCENTAGE" ? "100" : "9999999999.99"
              }
              step="0.01"
              value={form.discount_value}
              onChange={(e) =>
                setForm({ ...form, discount_value: e.target.value })
              }
            />
          )}
          <Field
            label="Minimum purchase (₹)"
            type="number"
            required
            min={
              form.discount_type === "FLAT_AMOUNT" ? form.discount_value : "0"
            }
            max="9999999999.99"
            step="0.01"
            value={form.minimum_purchase}
            onChange={(e) =>
              setForm({ ...form, minimum_purchase: e.target.value })
            }
          />
          {form.discount_type === "PERCENTAGE" && (
            <Field
              label="Maximum discount (₹, optional)"
              type="number"
              min="0.01"
              max="9999999999.99"
              step="0.01"
              value={form.maximum_discount || ""}
              onChange={(e) =>
                setForm({ ...form, maximum_discount: e.target.value || null })
              }
            />
          )}
          <label>
            Customer audience
            <select
              value={form.customer_type}
              onChange={(e) =>
                setForm({
                  ...form,
                  customer_type: e.target.value as OfferFields["customer_type"],
                })
              }
            >
              <option value="ALL">All customers</option>
              <option value="NEW_CUSTOMERS">New customers</option>
              <option value="EXISTING_CUSTOMERS">Existing customers</option>
            </select>
          </label>
          <Field
            label="Offer image URL (optional)"
            type="url"
            maxLength={2048}
            value={form.image_url}
            onChange={(e) => setForm({ ...form, image_url: e.target.value })}
          />
          <Field
            label="Offer starts"
            type="datetime-local"
            required
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <Field
            label="Offer expires"
            type="datetime-local"
            required
            min={start}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <small>
          Dates use your device timezone:{" "}
          {Intl.DateTimeFormat().resolvedOptions().timeZone}. Expiry is
          exclusive.
        </small>
        <label>
          Offer terms
          <textarea
            required
            minLength={3}
            maxLength={4000}
            rows={4}
            value={form.terms_conditions}
            onChange={(e) =>
              setForm({ ...form, terms_conditions: e.target.value })
            }
          />
        </label>
        <small>
          Describe eligible items, exclusions, BOGO/free-item details, and any
          customer restrictions.
        </small>
        <Feedback error={save.error} />
        <div className="action-row">
          <button className="button">Save offer draft</button>
          {offer && (
            <button
              type="button"
              className="text-button"
              onClick={() => done()}
            >
              Cancel offer edit
            </button>
          )}
        </div>
      </fieldset>
    </form>
  );
}
function OfferCard({ offer, edit }: { offer: Offer; edit: () => void }) {
  const client = useQueryClient(),
    [confirmArchive, setConfirmArchive] = useState(false);
  const action = useMutation({
    mutationFn: (value: string) =>
      mutate<Offer>(
        `/merchant/offers/${offer.id}/actions`,
        { action: value, revision: offer.revision },
        "POST",
      ),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["merchant-offers"] }),
  });
  return (
    <article className="offer-manage-card">
      <div className="section-heading">
        <h3>{offer.title}</h3>
        <span className="badge">{offer.status.replaceAll("_", " ")}</span>
      </div>
      <p>
        {discountLabel(offer)} ·{" "}
        {offer.store_id ? "Selected branch" : "All eligible branches"}
      </p>
      <p>
        {new Date(offer.starts_at).toLocaleString()} –{" "}
        {new Date(offer.expires_at).toLocaleString()}
      </p>
      {offer.admin_hold && (
        <p className="notice">
          An administrator must review this offer before it can go live.
        </p>
      )}
      {offer.moderation_note && <p>Review note: {offer.moderation_note}</p>}
      <Feedback error={action.error} />
      <div className="action-row">
        {offer.status !== "ARCHIVED" && (
          <button className="text-button" onClick={edit}>
            Edit offer: {offer.title}
          </button>
        )}
        {["DRAFT", "REJECTED", "PAUSED"].includes(offer.status) && (
          <button
            className="button"
            disabled={action.isPending}
            onClick={() => action.mutate("SUBMIT")}
          >
            {offer.status === "PAUSED" && offer.approved && !offer.admin_hold
              ? "Resume offer"
              : "Submit offer"}
          </button>
        )}
        {["ACTIVE", "PENDING_APPROVAL"].includes(offer.status) && (
          <button
            className="button secondary"
            disabled={action.isPending}
            onClick={() => action.mutate("PAUSE")}
          >
            Pause offer
          </button>
        )}
        {offer.status !== "ARCHIVED" && (
          <button
            className="text-button danger"
            onClick={() => setConfirmArchive(true)}
          >
            Archive offer
          </button>
        )}
      </div>
      {confirmArchive && (
        <div className="notice">
          <p>
            Archive this offer? It will be hidden and cannot be edited again.
          </p>
          <button
            className="button secondary"
            disabled={action.isPending}
            onClick={() => action.mutate("ARCHIVE")}
          >
            Confirm archive
          </button>
          <button
            className="text-button"
            onClick={() => setConfirmArchive(false)}
          >
            Keep offer
          </button>
        </div>
      )}
    </article>
  );
}
export default function MerchantOffers() {
  const [offset, setOffset] = useState(0),
    [editing, setEditing] = useState<Offer | null>(null),
    [version, setVersion] = useState(0),
    [notice, setNotice] = useState("");
  const profile = useQuery({
    queryKey: ["merchant-profile"],
    queryFn: () => authorized<Merchant | null>("/merchant/profile"),
    retry: false,
  });
  const categories = useQuery({
    queryKey: ["offer-categories"],
    queryFn: () => raw<Category[]>("/categories"),
    retry: false,
  });
  const stores = useQuery({
    queryKey: ["merchant-stores"],
    queryFn: () => authorized<Store[]>("/merchant/stores"),
    enabled: !!profile.data,
    retry: false,
  });
  const config = useQuery({
    queryKey: ["offer-config"],
    queryFn: () =>
      authorized<{ moderation_enabled: boolean }>("/merchant/offers/config"),
    retry: false,
  });
  const query = useQuery({
    queryKey: ["merchant-offers", offset],
    queryFn: () => authorized<Offer[]>(`/merchant/offers?offset=${offset}`),
    enabled: !!profile.data,
    retry: false,
  });
  return (
    <section className="account-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Give people a reason to visit</p>
          <h2>Your offers</h2>
        </div>
        <button
          className="text-button"
          disabled={!profile.data || query.isFetching}
          onClick={() => {
            setEditing(null);
            setVersion((v) => v + 1);
            void query.refetch();
          }}
        >
          Reload offers
        </button>
      </div>
      <p>
        {!config.data
          ? "Save a draft, then submit it when ready."
          : config.data.moderation_enabled
            ? "New and edited offers need admin approval before appearing to shoppers."
            : "Save a draft, then submit it to publish when your business and branch are eligible."}
      </p>
      <Feedback success={notice} />
      {!profile.data ? (
        <p>Complete your business profile to manage offers.</p>
      ) : (
        <>
          <QueryState
            pending={query.isPending}
            error={query.error}
            retry={query.refetch}
          />
          {query.data?.length === 0 && (
            <p>No offers yet. Create your first draft below.</p>
          )}
          {query.data?.map((offer) => (
            <OfferCard
              key={offer.id + offer.revision}
              offer={offer}
              edit={() => {
                setEditing(offer);
                setNotice("");
              }}
            />
          ))}
          <div className="action-row">
            <button
              className="text-button"
              disabled={offset === 0 || query.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Previous offers
            </button>
            <span>Page {offset / 25 + 1}</span>
            <button
              className="text-button"
              disabled={query.data?.length !== 25 || query.isFetching}
              onClick={() => setOffset(offset + 25)}
            >
              More offers
            </button>
          </div>
        </>
      )}
      {profile.data?.status !== "VERIFIED" ? (
        <p className="notice">
          Your business must be verified to create or edit offers.
        </p>
      ) : (
        <>
          <QueryState
            pending={categories.isPending || stores.isPending}
            error={categories.error || stores.error}
            retry={() => {
              void categories.refetch();
              void stores.refetch();
            }}
          />
          {categories.data?.length === 0 && (
            <p className="notice">
              Ask a platform administrator to add an active offer category.
            </p>
          )}
          {!!categories.data?.length && stores.data && (
            <OfferForm
              key={(editing?.id || "new") + version}
              offer={editing}
              categories={categories.data}
              stores={stores.data}
              done={(saved) => {
                setEditing(null);
                setVersion((v) => v + 1);
                setNotice(
                  saved ? "Offer draft saved. Submit it when ready." : "",
                );
              }}
            />
          )}
        </>
      )}
    </section>
  );
}
