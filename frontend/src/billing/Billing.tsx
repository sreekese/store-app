import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { Feedback, QueryState } from "../profiles/shared";
interface Plan {
  id: string;
  revision: number;
  name: string;
  description: string;
  currency: string;
  amount_minor: number;
  period_days: number;
  is_active: boolean;
}
interface Payment {
  id: string;
  merchant_name: string;
  plan_name: string;
  currency: string;
  amount_minor: number;
  period_days: number;
  status: string;
  created_at: string;
  paid_at: string | null;
  starts_at: string | null;
  expires_at: string | null;
  provider: string;
}
interface Page<T> {
  items: T[];
  next_offset: number | null;
}
function amount(row: { currency: string; amount_minor: number }) {
  return `${row.currency} ${(row.amount_minor / 100).toFixed(2)}`;
}
function Pager({
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
function PlanEditor({
  row,
  saved,
  close,
}: {
  row?: Plan;
  saved: () => void;
  close: () => void;
}) {
  const [data, setData] = useState({
    name: row?.name || "",
    description: row?.description || "",
    currency: row?.currency || "INR",
    amount_minor: row?.amount_minor || 0,
    period_days: row?.period_days || 30,
    is_active: row?.is_active || false,
  });
  const mutation = useMutation({
    mutationFn: () =>
      authorized(row ? `/billing/plans/${row.id}` : "/billing/plans", {
        method: row ? "PUT" : "POST",
        body: JSON.stringify({
          ...data,
          ...(row ? { revision: row.revision } : {}),
        }),
      }),
    onSuccess: saved,
  });
  return (
    <section className="account-panel">
      <h2>{row ? "Edit plan" : "Create plan"}</h2>
      <p>
        Prices are configured explicitly. Editing a plan does not change
        existing orders. No automatic renewal or coupon restrictions are
        applied.
      </p>
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset className="ad-fields" disabled={mutation.isPending}>
          <label>
            Plan name
            <input
              required
              minLength={2}
              maxLength={100}
              value={data.name}
              onChange={(e) => setData({ ...data, name: e.target.value })}
            />
          </label>
          <label>
            Description
            <textarea
              required
              minLength={3}
              maxLength={1000}
              value={data.description}
              onChange={(e) =>
                setData({ ...data, description: e.target.value })
              }
            />
          </label>
          <label>
            Currency
            <select
              value={data.currency}
              onChange={(e) => setData({ ...data, currency: e.target.value })}
            >
              {["INR", "USD", "EUR", "GBP"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            Price in minor units (100 = 1 currency unit)
            <input
              type="number"
              required
              min={1}
              max={100000000}
              step={1}
              value={data.amount_minor}
              onChange={(e) =>
                setData({ ...data, amount_minor: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Prepaid period in days
            <input
              type="number"
              required
              min={1}
              max={366}
              step={1}
              value={data.period_days}
              onChange={(e) =>
                setData({ ...data, period_days: Number(e.target.value) })
              }
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={data.is_active}
              onChange={(e) =>
                setData({ ...data, is_active: e.target.checked })
              }
            />
            Available to merchants
          </label>
          <button className="button">Save plan</button>
        </fieldset>
        <Feedback error={mutation.error} />
      </form>
      <button onClick={close}>Close editor</button>
    </section>
  );
}
function PaymentCard({
  row,
  superadmin,
  refresh,
}: {
  row: Payment;
  superadmin: boolean;
  refresh: () => void;
}) {
  const [reason, setReason] = useState("");
  const invoice = useMutation({
    mutationFn: () =>
      authorized<{
        number: string;
        kind: string;
        issued_at: string;
        payment: Payment;
      }>(`/billing/payments/${row.id}/invoice`),
  });
  const refund = useMutation({
    mutationFn: () =>
      authorized<{ status: string }>(`/billing/payments/${row.id}/refund`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    onSuccess: refresh,
  });
  return (
    <article className="notification-item">
      <h3>{row.plan_name}</h3>
      <p>
        {superadmin ? row.merchant_name + " · " : ""}
        {amount(row)} · {row.status} · Sandbox
      </p>
      <p>Order {row.id}</p>
      <p>Created {new Date(row.created_at).toLocaleString()}</p>
      {row.starts_at && row.expires_at && (
        <p>
          Period: {new Date(row.starts_at).toLocaleString()} –{" "}
          {new Date(row.expires_at).toLocaleString()}
        </p>
      )}
      {row.status === "PENDING" && (
        <p>
          Awaiting a verified provider webhook. This sandbox order does not
          charge money.
        </p>
      )}
      {row.paid_at && (
        <button disabled={invoice.isPending} onClick={() => invoice.mutate()}>
          View sandbox invoice
        </button>
      )}
      <Feedback error={invoice.error} />
      {invoice.data && (
        <section aria-label="Sandbox invoice">
          <h4>Sandbox invoice — not a tax invoice</h4>
          <p>{invoice.data.number}</p>
          <p>
            {invoice.data.payment.merchant_name} ·{" "}
            {invoice.data.payment.plan_name}
          </p>
          <p>
            {amount(invoice.data.payment)} · {invoice.data.payment.status}
          </p>
          <p>Issued {new Date(invoice.data.issued_at).toLocaleString()}</p>
          <button
            onClick={() => {
              const blob = new Blob([JSON.stringify(invoice.data, null, 2)], {
                type: "application/json",
              });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = invoice.data!.number + ".json";
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}
          >
            Download sandbox invoice
          </button>
        </section>
      )}
      {superadmin && row.status === "PAID" && (
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            refund.mutate();
          }}
        >
          <label>
            Full refund reason
            <input
              required
              minLength={5}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button disabled={refund.isPending || !!refund.data}>
            Request full sandbox refund
          </button>
          <p>
            The payment remains paid until a verified refund webhook arrives.
          </p>
        </form>
      )}
      <Feedback
        error={refund.error}
        success={
          refund.data
            ? `Refund ${refund.data.status.toLowerCase()}; awaiting confirmation.`
            : undefined
        }
      />
    </article>
  );
}
export default function Billing({
  superadmin = false,
}: {
  superadmin?: boolean;
}) {
  const auth = useAuth(),
    client = useQueryClient(),
    [planOffset, setPlanOffset] = useState(0),
    [paymentOffset, setPaymentOffset] = useState(0),
    [editor, setEditor] = useState<Plan | null | undefined>(),
    [selected, setSelected] = useState<{ plan: Plan; key: string } | null>(
      null,
    );
  const plans = useQuery({
    queryKey: ["billing-plans", auth.user?.id, planOffset],
    queryFn: () =>
      authorized<Page<Plan>>(`/billing/plans?offset=${planOffset}`),
    retry: false,
    gcTime: 0,
  });
  const payments = useQuery({
    queryKey: ["billing-payments", auth.user?.id, paymentOffset],
    queryFn: () =>
      authorized<Page<Payment>>(`/billing/payments?offset=${paymentOffset}`),
    retry: false,
    gcTime: 0,
    refetchInterval: 15000,
  });
  const config = useQuery({
    queryKey: ["billing-config", auth.user?.id],
    queryFn: () =>
      authorized<{ enabled: boolean; provider: string }>("/billing/config"),
    retry: false,
    gcTime: 0,
  });
  const subscription = useQuery({
    queryKey: ["billing-subscription", auth.user?.id],
    queryFn: () =>
      authorized<{ status: string; payment: Payment | null }>(
        "/billing/subscription",
      ),
    enabled: !superadmin,
    retry: false,
    gcTime: 0,
    refetchInterval: 15000,
  });
  function refresh() {
    void client.invalidateQueries({ queryKey: ["billing-payments"] });
    void client.invalidateQueries({ queryKey: ["billing-subscription"] });
  }
  const order = useMutation({
    mutationFn: () =>
      authorized<Payment>("/billing/orders", {
        method: "POST",
        body: JSON.stringify({
          plan_id: selected!.plan.id,
          plan_revision: selected!.plan.revision,
          request_key: selected!.key,
        }),
      }),
    onSuccess: () => {
      setSelected(null);
      refresh();
    },
  });
  return (
    <>
      <header className="header">
        <Link
          className="brand"
          to={superadmin ? "/superadmin/dashboard" : "/merchant/dashboard"}
        >
          ✳ nearperk.
        </Link>
        <Link to={superadmin ? "/superadmin/dashboard" : "/merchant/dashboard"}>
          Back to dashboard
        </Link>
      </header>
      <main className="container workspace-shell ad-manager">
        <h1>
          {superadmin ? "Plans and payments" : "Billing and subscription"}
        </h1>
        <p className="notice">
          Sandbox billing only. No real charges. Prepaid periods do not renew
          automatically. Coupon claims, redemptions and advertisement
          eligibility are unchanged.
        </p>
        <QueryState
          pending={config.isPending}
          error={config.error}
          retry={config.refetch}
        />
        {config.data && !config.isError && !config.data.enabled && (
          <p>Checkout is not configured.</p>
        )}
        {!superadmin && (
          <section className="account-panel">
            <h2>Subscription</h2>
            <QueryState
              pending={subscription.isPending}
              error={subscription.error}
              retry={subscription.refetch}
            />
            {subscription.data && !subscription.isError && (
              <>
                <p>{subscription.data.status}</p>
                {subscription.data.payment && (
                  <p>
                    {subscription.data.payment.plan_name} · Ends{" "}
                    {new Date(
                      subscription.data.payment.expires_at!,
                    ).toLocaleString()}
                  </p>
                )}
              </>
            )}
          </section>
        )}
        {superadmin && (
          <button onClick={() => setEditor(null)}>New plan</button>
        )}
        {editor !== undefined && (
          <PlanEditor
            key={editor?.id + "-" + editor?.revision}
            row={editor || undefined}
            close={() => setEditor(undefined)}
            saved={() => {
              setEditor(undefined);
              void client.invalidateQueries({ queryKey: ["billing-plans"] });
            }}
          />
        )}
        <section className="account-panel">
          <h2>Subscription plans</h2>
          <button onClick={() => void plans.refetch()}>Refresh plans</button>
          <QueryState
            pending={plans.isPending}
            error={plans.error}
            retry={plans.refetch}
          />
          {plans.data && !plans.isError && (
            <>
              {!plans.data.items.length && <p>No plans have been published.</p>}
              {plans.data.items.map((p) => (
                <article className="notification-item" key={p.id}>
                  <h3>{p.name}</h3>
                  <p>{p.description}</p>
                  <p>
                    {amount(p)} · {p.period_days} days
                    {superadmin
                      ? ` · ${p.is_active ? "Available" : "Inactive"}`
                      : ""}
                  </p>
                  {superadmin ? (
                    <button onClick={() => setEditor(p)}>Edit {p.name}</button>
                  ) : (
                    <button
                      disabled={
                        !config.data?.enabled ||
                        config.isError ||
                        order.isPending
                      }
                      onClick={() => {
                        order.reset();
                        setSelected({ plan: p, key: crypto.randomUUID() });
                      }}
                    >
                      Review {p.name}
                    </button>
                  )}
                </article>
              ))}
              <Pager
                offset={planOffset}
                next={plans.data.next_offset}
                change={setPlanOffset}
              />
            </>
          )}
        </section>
        {selected && (
          <section className="account-panel">
            <h2>Review sandbox order</h2>
            <p>
              {selected.plan.name} · {amount(selected.plan)} ·{" "}
              {selected.plan.period_days} days
            </p>
            <p>
              This creates a test order. Activation requires a verified provider
              webhook; no money is collected.
            </p>
            <button
              disabled={
                order.isPending || !config.data?.enabled || config.isError
              }
              onClick={() => order.mutate()}
            >
              Create sandbox order
            </button>
            <button
              disabled={order.isPending}
              onClick={() => setSelected(null)}
            >
              Cancel
            </button>
            <Feedback error={order.error} />
          </section>
        )}
        {order.isSuccess && (
          <p role="status">Order saved. Awaiting payment confirmation.</p>
        )}
        <section className="account-panel">
          <h2>Payment history</h2>
          <button onClick={refresh}>Refresh payments</button>
          <QueryState
            pending={payments.isPending}
            error={payments.error}
            retry={payments.refetch}
          />
          {payments.data && !payments.isError && (
            <>
              {!payments.data.items.length && <p>No payment records.</p>}
              {payments.data.items.map((p) => (
                <PaymentCard
                  key={p.id + "-" + p.status}
                  row={p}
                  superadmin={superadmin}
                  refresh={refresh}
                />
              ))}
              <Pager
                offset={paymentOffset}
                next={payments.data.next_offset}
                change={setPaymentOffset}
              />
            </>
          )}
        </section>
      </main>
    </>
  );
}
