import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized, raw } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { Feedback, QueryState } from "../profiles/shared";
export interface Review {
  id: string;
  rating: number;
  comment: string;
  status: string;
  revision: number;
  moderation_reason: string;
  store_id: string;
  created_at: string;
}
export interface Page<T> {
  items: T[];
  next_offset: number | null;
}
export function Pager({
  offset,
  next,
  change,
}: {
  offset: number;
  next: number | null;
  change: (value: number) => void;
}) {
  return (
    <div className="form-actions">
      <button
        disabled={!offset}
        onClick={() => change(Math.max(0, offset - 20))}
      >
        Previous page
      </button>
      <button
        disabled={next === null}
        onClick={() => next !== null && change(next)}
      >
        Next page
      </button>
    </div>
  );
}
export function ReviewForm({ redemptionId }: { redemptionId: string }) {
  const auth = useAuth(),
    client = useQueryClient(),
    [rating, setRating] = useState(5),
    [comment, setComment] = useState("");
  const query = useQuery({
    queryKey: ["own-review", auth.user?.id, redemptionId],
    queryFn: () =>
      authorized<{ review: Review | null }>(
        `/trust/reviews/mine/${redemptionId}`,
      ),
    retry: false,
    gcTime: 0,
  });
  const save = useMutation({
    mutationFn: () =>
      authorized("/trust/reviews", {
        method: "POST",
        body: JSON.stringify({ redemption_id: redemptionId, rating, comment }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["own-review"] });
    },
  });
  return (
    <section className="account-panel">
      <h2>Review your redeemed offer</h2>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      <Feedback
        error={save.error}
        success={
          save.isSuccess ? "Review submitted for moderation." : undefined
        }
      />
      {query.data &&
        !query.isError &&
        (query.data.review ? (
          <>
            <p>
              {query.data.review.rating}/5 · {query.data.review.status}
            </p>
            <p>{query.data.review.comment}</p>
            {query.data.review.moderation_reason && (
              <p>Moderation note: {query.data.review.moderation_reason}</p>
            )}
          </>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <p>
              One review per successful redemption. Reviews appear after
              moderation. Do not include personal details or coupon codes.
            </p>
            <label>
              Rating
              <select
                value={rating}
                onChange={(e) => setRating(Number(e.target.value))}
              >
                {[5, 4, 3, 2, 1].map((n) => (
                  <option key={n} value={n}>
                    {n} / 5
                  </option>
                ))}
              </select>
            </label>
            <label>
              Your experience
              <textarea
                required
                minLength={1}
                maxLength={2000}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </label>
            <button
              className="button"
              disabled={save.isPending || !comment.trim()}
            >
              Submit review
            </button>
          </form>
        ))}
    </section>
  );
}
export default function Reviews({
  offerId,
  storeId,
}: {
  offerId: string;
  storeId: string;
}) {
  const auth = useAuth(),
    [offset, setOffset] = useState(0),
    [scope, setScope] = useState("offer");
  const query = useQuery({
    queryKey: ["public-reviews", storeId, offerId, scope, offset],
    queryFn: () =>
      raw<Page<Review> & { count: number; average: number | null }>(
        `/trust/reviews?store_id=${storeId}${scope === "offer" ? `&offer_id=${offerId}` : ""}&offset=${offset}`,
      ),
    retry: false,
  });
  return (
    <section className="account-panel">
      <h2>Verified redemption reviews</h2>
      <label>
        Reviews for
        <select
          value={scope}
          onChange={(e) => {
            setScope(e.target.value);
            setOffset(0);
          }}
        >
          <option value="offer">This offer at this branch</option>
          <option value="store">All offers at this branch</option>
        </select>
      </label>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && !query.isError && (
        <>
          <p>
            {query.data.count
              ? `${query.data.average}/5 from ${query.data.count} reviews`
              : "No published reviews yet."}
          </p>
          {query.data.items.map((r) => (
            <article className="notification-item" key={r.id}>
              <strong>{r.rating}/5 · Verified redemption</strong>
              <p>{r.comment}</p>
              <small>{new Date(r.created_at).toLocaleDateString()}</small>
              {auth.user?.role === "USER" && (
                <p>
                  <Link
                    to={`/app/support?target=REVIEW&id=${r.id}&store=${r.store_id}`}
                  >
                    Report review
                  </Link>
                </p>
              )}
            </article>
          ))}
          <Pager
            offset={offset}
            next={query.data.next_offset}
            change={setOffset}
          />
        </>
      )}
    </section>
  );
}
export function ReviewModeration() {
  const [status, setStatus] = useState("PENDING"),
    [offset, setOffset] = useState(0),
    auth = useAuth();
  const query = useQuery({
    queryKey: ["review-moderation", auth.user?.id, status, offset],
    queryFn: () =>
      authorized<Page<Review>>(
        `/trust/reviews/moderation?status=${status}&offset=${offset}`,
      ),
    retry: false,
    gcTime: 0,
  });
  return (
    <section className="account-panel">
      <h2>Review moderation</h2>
      <label>
        Review status
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          {["PENDING", "PUBLISHED", "HIDDEN"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && !query.isError && (
        <>
          {!query.data.items.length && <p>No reviews in this queue.</p>}
          {query.data.items.map((r) => (
            <ModerationItem key={`${r.id}-${r.revision}`} review={r} />
          ))}
          <Pager
            offset={offset}
            next={query.data.next_offset}
            change={setOffset}
          />
        </>
      )}
    </section>
  );
}
function ModerationItem({ review }: { review: Review }) {
  const [reason, setReason] = useState(""),
    [status, setStatus] = useState(
      review.status === "PUBLISHED" ? "HIDDEN" : "PUBLISHED",
    ),
    client = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      authorized(`/trust/reviews/${review.id}/moderate`, {
        method: "POST",
        body: JSON.stringify({ revision: review.revision, status, reason }),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["review-moderation"] });
      void client.invalidateQueries({ queryKey: ["public-reviews"] });
    },
  });
  return (
    <article className="notification-item">
      <p>
        <strong>{review.rating}/5</strong> · {review.status}
      </p>
      <p>{review.comment}</p>
      {review.moderation_reason && (
        <p>Previous decision: {review.moderation_reason}</p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <label>
          Decision
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["PUBLISHED", "HIDDEN"]
              .filter((s) => s !== review.status)
              .map((s) => (
                <option key={s}>{s}</option>
              ))}
          </select>
        </label>
        <label>
          Moderation reason
          <textarea
            required
            maxLength={1000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <button disabled={save.isPending || !reason.trim()}>
          Save moderation decision
        </button>
        <Feedback error={save.error} />
      </form>
    </article>
  );
}
