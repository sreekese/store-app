import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Feedback, mutate, QueryState, type Merchant } from "./shared";
const transitions: Record<string, string[]> = {
  PENDING: ["UNDER_REVIEW", "VERIFIED", "REJECTED"],
  UNDER_REVIEW: ["VERIFIED", "REJECTED"],
  VERIFIED: ["SUSPENDED"],
  REJECTED: ["UNDER_REVIEW"],
  SUSPENDED: ["UNDER_REVIEW"],
};
const actionLabel: Record<string, string> = {
  UNDER_REVIEW: "Start review",
  VERIFIED: "Approve business",
  REJECTED: "Reject business",
  SUSPENDED: "Suspend business",
};
interface Audit {
  id: string;
  action: string;
  created_at: string;
  detail: { note?: string; status?: string };
}
function ReviewCard({ merchant }: { merchant: Merchant }) {
  const [note, setNote] = useState(""),
    [showAudit, setShowAudit] = useState(false),
    client = useQueryClient();
  const audit = useQuery({
    queryKey: ["merchant-audit", merchant.id],
    queryFn: () => authorized<Audit[]>(`/admin/merchants/${merchant.id}/audit`),
    enabled: showAudit,
    retry: false,
  });
  const review = useMutation({
    mutationFn: (status: string) =>
      mutate<Merchant>(`/admin/merchants/${merchant.id}/review`, {
        status,
        note,
        revision: merchant.revision,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["merchant-reviews"] });
      await client.invalidateQueries({
        queryKey: ["merchant-audit", merchant.id],
      });
    },
  });
  return (
    <article className="account-panel review-card">
      <div className="section-heading">
        <h3>{merchant.business_name}</h3>
        <span className="badge">{merchant.status.replaceAll("_", " ")}</span>
      </div>
      <p>
        {merchant.category} · {merchant.contact_email} · {merchant.phone}
      </p>
      <p>{merchant.description || "No business description provided."}</p>
      <div className="action-row">
        {[
          ["Website", merchant.website],
          ["Logo image", merchant.logo_url],
          ["Cover image", merchant.cover_image_url],
        ].map(([label, url]) =>
          url ? (
            <a
              key={label}
              className="text-button"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {label}
            </a>
          ) : null,
        )}
      </div>
      {merchant.review_note && (
        <p className="notice">Previous review: {merchant.review_note}</p>
      )}
      <form className="auth-form" onSubmit={(e) => e.preventDefault()}>
        <label>
          Review note for {merchant.business_name}
          <textarea
            maxLength={1000}
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Required for rejection or suspension; visible to the merchant."
          />
        </label>
        <Feedback error={review.error} />
        <div className="action-row">
          {transitions[merchant.status]?.map((status) => (
            <button
              key={status}
              type="button"
              className={
                status === "REJECTED" || status === "SUSPENDED"
                  ? "button secondary"
                  : "button"
              }
              disabled={
                review.isPending ||
                (["REJECTED", "SUSPENDED"].includes(status) && !note.trim())
              }
              onClick={() => review.mutate(status)}
            >
              {actionLabel[status]}
            </button>
          ))}
        </div>
      </form>
      <button
        className="text-button"
        aria-expanded={showAudit}
        onClick={() => setShowAudit(!showAudit)}
      >
        {showAudit ? "Hide history" : "View audit history"}
      </button>
      {showAudit && (
        <div>
          <QueryState
            pending={audit.isPending}
            error={audit.error}
            retry={audit.refetch}
          />
          <ul className="audit-list">
            {audit.data?.map((event) => (
              <li key={event.id}>
                {event.action.replaceAll("_", " ")} ·{" "}
                {new Date(event.created_at).toLocaleString()}
                {event.detail.status && <span> · {event.detail.status}</span>}
                {event.detail.note && <p>{event.detail.note}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
export default function AdminReviews() {
  const [status, setStatus] = useState("PENDING"),
    [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["merchant-reviews", status, offset],
    queryFn: () =>
      authorized<Merchant[]>(
        `/admin/merchants?offset=${offset}${status ? "&status=" + status : ""}`,
      ),
    retry: false,
  });
  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Build a trusted neighbourhood</p>
          <h2>Merchant verification</h2>
        </div>
        <label className="filter-label">
          Verification status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            {[
              "PENDING",
              "UNDER_REVIEW",
              "VERIFIED",
              "REJECTED",
              "SUSPENDED",
              "",
            ].map((value) => (
              <option key={value} value={value}>
                {value ? value.replaceAll("_", " ") : "All businesses"}
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
      {query.data?.length === 0 && (
        <p className="account-panel empty-state">
          No businesses in this queue.
        </p>
      )}
      {query.data?.map((merchant) => (
        <ReviewCard key={merchant.id + merchant.revision} merchant={merchant} />
      ))}
      <div className="action-row pagination">
        <button
          className="text-button"
          disabled={offset === 0 || query.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Previous
        </button>
        <span>Page {offset / 25 + 1}</span>
        <button
          className="text-button"
          disabled={query.data?.length !== 25 || query.isFetching}
          onClick={() => setOffset(offset + 25)}
        >
          Next
        </button>
        <button
          className="text-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Reload queue
        </button>
      </div>
    </section>
  );
}
