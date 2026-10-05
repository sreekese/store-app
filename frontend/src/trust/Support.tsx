import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { homePaths, labels, type Role } from "../auth/types";
import { Feedback, QueryState } from "../profiles/shared";
import { Pager, ReviewModeration, type Page } from "./Reviews";
interface Case {
  id: string;
  reference: string;
  title: string;
  store_name: string;
  reason: string;
  status: string;
  revision: number;
  description: string;
  resolution: string;
  claim_id: string | null;
  redemption_id: string | null;
  created_at: string;
  resolved_at: string | null;
  context: {
    offer?: { terms_conditions: string; minimum_purchase: string };
    eligibility?: string;
    expires_at?: string;
    status_at_report?: string;
    receipt?: {
      purchase_amount: string;
      discount_amount: string;
      redeemed_at: string;
    };
    comment?: string;
    rating?: number;
  };
}
interface Action {
  id: string;
  actor_role: Role;
  kind: string;
  message: string;
  status: string;
  created_at: string;
  revision: number;
}
const states = ["OPEN", "UNDER_REVIEW", "AWAITING_RESPONSE", "RESOLVED"];
const reasons = [
  "STORE_REFUSED_COUPON",
  "INVALID_OFFER",
  "MERCHANT_CLOSED",
  "INCORRECT_DISCOUNT",
  "FRAUDULENT_LISTING",
  "INAPPROPRIATE_CONTENT",
  "OTHER",
];
export const supportPath = (role: Role) =>
  homePaths[role].replace(/\/dashboard$/, "") + "/support";
export function ReportForm({
  target,
  id,
  stores,
}: {
  target: string;
  id: string;
  stores: { id: string; name: string }[];
}) {
  const [store, setStore] = useState(stores[0]?.id || ""),
    [reason, setReason] = useState(
      target === "CLAIM" ? "STORE_REFUSED_COUPON" : "OTHER",
    ),
    [description, setDescription] = useState("");
  const save = useMutation({
    mutationFn: () =>
      authorized<Case>("/trust/cases", {
        method: "POST",
        body: JSON.stringify({
          target_type: target,
          target_id: id,
          store_id: store,
          reason,
          description,
        }),
      }),
  });
  return (
    <section className="account-panel">
      <h2>Report an issue</h2>
      <p>
        Your description and replies are shared with platform support and the
        relevant store team. Do not include passwords, payment details, or
        private coupon codes.
      </p>
      {save.data ? (
        <p role="status">
          Case created:{" "}
          <Link to={`/app/support/${save.data.id}`}>{save.data.reference}</Link>
        </p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <label>
            Affected branch
            <select
              required
              value={store}
              onChange={(e) => setStore(e.target.value)}
            >
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Issue
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              {reasons
                .filter(
                  (r) => target === "CLAIM" || r !== "STORE_REFUSED_COUPON",
                )
                .map((r) => (
                  <option key={r} value={r}>
                    {r.replaceAll("_", " ")}
                  </option>
                ))}
            </select>
          </label>
          <label>
            What happened?
            <textarea
              required
              minLength={10}
              maxLength={2000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <button
            className="button"
            disabled={
              save.isPending || description.trim().length < 10 || !store
            }
          >
            Submit report
          </button>
          <Feedback error={save.error} />
        </form>
      )}
    </section>
  );
}
export default function Support({ role }: { role: Role }) {
  const { id } = useParams(),
    [search] = useSearchParams(),
    admin = role === "ADMIN" || role === "SUPER_ADMIN";
  const target = search.get("target"),
    targetId = search.get("id"),
    store = search.get("store");
  return (
    <>
      <header className="header">
        <Link className="brand" to={homePaths[role]}>
          ✳ nearperk.
        </Link>
        <Link to={homePaths[role]}>Back to dashboard</Link>
      </header>
      <main className="container workspace-shell trust-shell">
        <h1>
          {role === "USER" ? "My support cases" : "Support and moderation"}
        </h1>
        {id ? (
          <CaseDetail key={id} id={id} role={role} />
        ) : (
          <>
            {role === "USER" &&
              targetId &&
              store &&
              ["OFFER", "STORE", "REVIEW"].includes(target || "") && (
                <ReportForm
                  key={`${target}-${targetId}`}
                  target={target!}
                  id={targetId}
                  stores={[{ id: store, name: "Selected branch" }]}
                />
              )}
            <CaseList role={role} />
            {admin && <ReviewModeration />}
          </>
        )}
      </main>
    </>
  );
}
function CaseList({ role }: { role: Role }) {
  const auth = useAuth(),
    [offset, setOffset] = useState(0),
    [status, setStatus] = useState("");
  const query = useQuery({
    queryKey: ["support-cases", auth.user?.id, status, offset],
    queryFn: () =>
      authorized<Page<Case>>(
        `/trust/cases?offset=${offset}${status ? `&status=${status}` : ""}`,
      ),
    retry: false,
    gcTime: 0,
  });
  return (
    <section className="account-panel">
      <h2>{role === "USER" ? "Your reports" : "Case queue"}</h2>
      {role === "USER" && (
        <p>
          Open a coupon or offer to report an issue.{" "}
          <Link to="/app/coupons">Go to my coupons</Link>
        </p>
      )}
      <label>
        Case status
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All cases</option>
          {states.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <button onClick={() => void query.refetch()} disabled={query.isFetching}>
        Refresh cases
      </button>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && !query.isError && (
        <>
          {!query.data.items.length && <p>No support cases here.</p>}
          {query.data.items.map((c) => (
            <article className="notification-item" key={c.id}>
              <h3>
                <Link to={`${supportPath(role)}/${c.id}`}>{c.title}</Link>
              </h3>
              <p>
                {c.store_name} · {c.reason.replaceAll("_", " ")} · {c.status}
              </p>
              <small>{c.reference}</small>
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
function CaseDetail({ id, role }: { id: string; role: Role }) {
  const auth = useAuth(),
    [offset, setOffset] = useState(0),
    client = useQueryClient();
  const query = useQuery({
    queryKey: ["support-case", auth.user?.id, id],
    queryFn: () => authorized<Case>(`/trust/cases/${id}`),
    retry: false,
    gcTime: 0,
  });
  const history = useQuery({
    queryKey: ["support-history", auth.user?.id, id, offset],
    queryFn: () =>
      authorized<Page<Action>>(`/trust/cases/${id}/history?offset=${offset}`),
    retry: false,
    gcTime: 0,
  });
  function refresh() {
    void query.refetch();
    void client.invalidateQueries({ queryKey: ["support-history"] });
    void client.invalidateQueries({ queryKey: ["support-cases"] });
  }
  const c = query.data;
  return (
    <>
      <Link to={supportPath(role)}>← All support cases</Link>
      <button disabled={query.isFetching} onClick={refresh}>
        Refresh case
      </button>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {c && !query.isError && (
        <>
          <section className="account-panel">
            <h2>{c.title}</h2>
            <p>{c.reference}</p>
            <p>
              {c.store_name} · {c.status} · {c.reason.replaceAll("_", " ")}
            </p>
            <p className="offer-terms">{c.description}</p>
            {c.claim_id && role === "USER" && (
              <Link to={`/app/coupons/${c.claim_id}`}>
                Open affected coupon
              </Link>
            )}
            {c.context.offer && (
              <>
                <h3>Terms preserved at claim time</h3>
                <p className="offer-terms">
                  {c.context.offer.terms_conditions}
                </p>
                <p>
                  Minimum purchase ₹{c.context.offer.minimum_purchase} ·{" "}
                  {c.context.eligibility?.replaceAll("_", " ")}
                </p>
                <p>Coupon status when reported: {c.context.status_at_report}</p>
                <p>
                  Expires {new Date(c.context.expires_at!).toLocaleString()}
                </p>
              </>
            )}
            {c.context.receipt && (
              <>
                <h3>Original redemption</h3>
                <p>
                  Purchase ₹{c.context.receipt.purchase_amount} · Benefit ₹
                  {c.context.receipt.discount_amount}
                </p>
                <p>Receipt {c.redemption_id}</p>
              </>
            )}
            {c.context.comment && (
              <blockquote>
                {c.context.rating}/5 · {c.context.comment}
              </blockquote>
            )}
            {c.resolution && (
              <div className="notice">
                <h3>Resolution</h3>
                <p>{c.resolution}</p>
                <p>{new Date(c.resolved_at!).toLocaleString()}</p>
              </div>
            )}
            <p>
              Support decisions preserve the original coupon and redemption
              records.
            </p>
          </section>
          {c.status !== "RESOLVED" && (
            <CaseReply
              key={c.revision}
              item={c}
              role={role}
              refresh={refresh}
            />
          )}
          <section className="account-panel">
            <h2>Case history</h2>
            <p>
              Newest first. Replies are visible to the shopper, relevant store
              team, and platform support.
            </p>
            <QueryState
              pending={history.isPending}
              error={history.error}
              retry={history.refetch}
            />
            {history.data && !history.isError && (
              <>
                {history.data.items.map((a) => (
                  <article className="notification-item" key={a.id}>
                    <strong>
                      {labels[a.actor_role]} · {a.kind.replaceAll("_", " ")} ·{" "}
                      {a.status}
                    </strong>
                    <p className="offer-terms">{a.message}</p>
                    <small>{new Date(a.created_at).toLocaleString()}</small>
                  </article>
                ))}
                <Pager
                  offset={offset}
                  next={history.data.next_offset}
                  change={setOffset}
                />
              </>
            )}
          </section>
        </>
      )}
    </>
  );
}
function CaseReply({
  item,
  role,
  refresh,
}: {
  item: Case;
  role: Role;
  refresh: () => void;
}) {
  const [message, setMessage] = useState(""),
    [status, setStatus] = useState(""),
    admin = role === "ADMIN" || role === "SUPER_ADMIN";
  const options =
    item.status === "OPEN"
      ? ["UNDER_REVIEW"]
      : item.status === "UNDER_REVIEW"
        ? ["AWAITING_RESPONSE", "RESOLVED"]
        : ["UNDER_REVIEW", "RESOLVED"];
  const save = useMutation({
    mutationFn: () =>
      authorized(
        `/trust/cases/${item.id}/${status ? "transition" : "respond"}`,
        {
          method: "POST",
          body: JSON.stringify({
            revision: item.revision,
            message,
            ...(status ? { status } : {}),
          }),
        },
      ),
    onSuccess: refresh,
  });
  return (
    <section className="account-panel">
      <h2>Respond to case</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {admin && (
          <label>
            Case action
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Add response</option>
              {options.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          {status === "RESOLVED" ? "Resolution" : "Response"}
          <textarea
            required
            maxLength={2000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </label>
        <button className="button" disabled={save.isPending || !message.trim()}>
          {status === "RESOLVED" ? "Resolve case" : "Send response"}
        </button>
        <Feedback error={save.error} />
      </form>
    </section>
  );
}
