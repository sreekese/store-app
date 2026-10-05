import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Feedback, mutate, QueryState } from "../profiles/shared";
import { discountLabel, type Offer } from "./types";
interface ReviewOffer extends Offer {
  business_name: string;
  category_name: string;
  store_name: string | null;
}
interface Audit {
  id: string;
  action: string;
  created_at: string;
  detail: { decision?: string; note?: string };
}
function ReviewCard({ offer }: { offer: ReviewOffer }) {
  const [note, setNote] = useState(""),
    [history, setHistory] = useState(false),
    client = useQueryClient();
  const review = useMutation({
    mutationFn: (action: string) =>
      mutate<Offer>(
        `/admin/offers/${offer.id}/review`,
        { action, note, revision: offer.revision },
        "POST",
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["offer-reviews"] });
      await client.invalidateQueries({ queryKey: ["offer-audit", offer.id] });
    },
  });
  const audit = useQuery({
    queryKey: ["offer-audit", offer.id],
    queryFn: () => authorized<Audit[]>(`/admin/offers/${offer.id}/audit`),
    enabled: history,
    retry: false,
  });
  return (
    <article className="offer-manage-card">
      <div className="section-heading">
        <h3>{offer.title}</h3>
        <span className="badge">{offer.status.replaceAll("_", " ")}</span>
      </div>
      <p>
        <strong>{offer.business_name}</strong> · {offer.category_name} ·{" "}
        {offer.store_name || "All eligible branches"}
      </p>
      <p>{offer.description}</p>
      <p>
        {discountLabel(offer)} · Minimum purchase ₹{offer.minimum_purchase}
        {offer.maximum_discount &&
          ` · Maximum discount ₹${offer.maximum_discount}`}
      </p>
      <p>Audience: {offer.customer_type.replaceAll("_", " ")}</p>
      <p>
        {new Date(offer.starts_at).toLocaleString()} –{" "}
        {new Date(offer.expires_at).toLocaleString()}
      </p>
      <p className="offer-terms">Terms: {offer.terms_conditions}</p>
      {offer.image_url && (
        <a
          className="text-button"
          href={offer.image_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          View offer image
        </a>
      )}
      {offer.moderation_note && (
        <p className="notice">Previous review: {offer.moderation_note}</p>
      )}
      <form className="auth-form" onSubmit={(e) => e.preventDefault()}>
        <label>
          Review note for {offer.title}
          <textarea
            rows={3}
            maxLength={1000}
            placeholder="Required for rejection or suspension; visible to the merchant."
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <Feedback error={review.error} />
        <div className="action-row">
          {offer.status === "PENDING_APPROVAL" && (
            <>
              <button
                type="button"
                className="button"
                disabled={review.isPending}
                onClick={() => review.mutate("APPROVE")}
              >
                Approve offer
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={review.isPending || !note.trim()}
                onClick={() => review.mutate("REJECT")}
              >
                Reject offer
              </button>
            </>
          )}
          {offer.status === "ACTIVE" && (
            <button
              type="button"
              className="button secondary"
              disabled={review.isPending || !note.trim()}
              onClick={() => review.mutate("SUSPEND")}
            >
              Suspend offer
            </button>
          )}
          {offer.status === "PAUSED" && offer.admin_hold && offer.approved && (
            <button
              type="button"
              className="button"
              disabled={review.isPending}
              onClick={() => review.mutate("REACTIVATE")}
            >
              Reactivate offer
            </button>
          )}
        </div>
      </form>
      <button
        className="text-button"
        aria-expanded={history}
        onClick={() => setHistory(!history)}
      >
        {history ? "Hide offer history" : "View offer history"}
      </button>
      {history && (
        <>
          <QueryState
            pending={audit.isPending}
            error={audit.error}
            retry={audit.refetch}
          />
          <ul className="audit-list">
            {audit.data?.map((item) => (
              <li key={item.id}>
                {item.action.replaceAll("_", " ")} · {item.detail.decision} ·{" "}
                {new Date(item.created_at).toLocaleString()}
                {item.detail.note && <p>{item.detail.note}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
export default function OfferModeration() {
  const [status, setStatus] = useState("PENDING_APPROVAL"),
    [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["offer-reviews", status, offset],
    queryFn: () =>
      authorized<ReviewOffer[]>(
        `/admin/offers?status=${status}&offset=${offset}`,
      ),
    retry: false,
  });
  return (
    <section className="account-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Clear terms. Trusted offers.</p>
          <h2>Offer moderation</h2>
        </div>
        <label className="filter-label">
          Offer review status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            {[
              "PENDING_APPROVAL",
              "ACTIVE",
              "PAUSED",
              "REJECTED",
              "EXPIRED",
              "DRAFT",
              "ARCHIVED",
            ].map((value) => (
              <option key={value} value={value}>
                {value.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
      </div>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data?.length === 0 && <p>No offers in this review queue.</p>}
      {query.data?.map((offer) => (
        <ReviewCard key={offer.id + offer.revision} offer={offer} />
      ))}
      <div className="action-row">
        <button
          className="text-button"
          disabled={offset === 0 || query.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Previous reviews
        </button>
        <span>Page {offset / 25 + 1}</span>
        <button
          className="text-button"
          disabled={query.data?.length !== 25 || query.isFetching}
          onClick={() => setOffset(offset + 25)}
        >
          More reviews
        </button>
        <button
          className="text-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Reload offer reviews
        </button>
      </div>
    </section>
  );
}
