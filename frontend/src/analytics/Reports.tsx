import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { homePaths } from "../auth/types";
import { Feedback, QueryState } from "../profiles/shared";
type Row = Record<string, string | number | null>;
interface Page {
  items: Row[];
  next_offset: number | null;
}
interface Report {
  scope: string;
  timezone: string;
  generated_at: string;
  as_of: string;
  start_date: string;
  end_date: string;
  summary: Record<string, string | number | null>;
  retention: {
    previous_start_date: string;
    previous_end_date: string;
    previous_active_merchants: number;
    retained_merchants: number;
    rate: string | null;
  };
  daily: Row[];
  events: Row[];
  campaigns: Page;
  merchants: Page;
  revenue?: Row[];
}
const labels: Record<string, string> = {
  id: "Reference",
  title: "Offer",
  status: "Current status",
  business_name: "Business",
  date: "Date",
  claims: "Claims",
  redemptions: "Redemptions during period",
  cohort_redeemed: "Claims redeemed by period end",
  cohort_rate: "Claim cohort redemption %",
  engaged_shoppers: "Engaged shoppers",
  kind: "Event",
  count: "Count",
  provider: "Provider",
  currency: "Currency",
  gross_minor: "Confirmed receipts (minor units)",
  refund_minor: "Confirmed refunds (minor units)",
  net_minor: "Net movement (minor units)",
  payments: "Confirmed payments",
};
function Table({
  rows,
  columns,
  chooseBusiness,
}: {
  rows: Row[];
  columns: string[];
  chooseBusiness?: (id: string) => void;
}) {
  return rows.length ? (
    <div
      className="report-table"
      tabIndex={0}
      aria-label="Scrollable report table"
    >
      <table>
        <thead>
          <tr>
            {columns.map((k) => (
              <th scope="col" key={k}>
                {labels[k] || k}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={String(r.id || r.date || r.kind || i)}>
              {columns.map((k) => (
                <td key={k}>
                  {k === "business_name" && chooseBusiness ? (
                    <button
                      className="text-button"
                      onClick={() => chooseBusiness(String(r.id))}
                    >
                      {r[k]}
                    </button>
                  ) : (
                    (r[k] ?? "—")
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p>No matching activity.</p>
  );
}
function Pages({
  offset,
  next,
  onChange,
}: {
  offset: number;
  next: number | null;
  onChange: (n: number) => void;
}) {
  return (
    <div className="action-row">
      <button
        disabled={!offset}
        onClick={() => onChange(Math.max(0, offset - 20))}
      >
        Previous
      </button>
      <button
        disabled={next === null}
        onClick={() => next !== null && onChange(next)}
      >
        Next
      </button>
    </div>
  );
}
function istDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
export default function Reports() {
  const auth = useAuth(),
    role = auth.user!.role,
    today = istDate(),
    [end, setEnd] = useState(today),
    [start, setStart] = useState(() => {
      const d = new Date(today + "T12:00:00Z");
      d.setUTCDate(d.getUTCDate() - 29);
      return d.toISOString().slice(0, 10);
    }),
    [business, setBusiness] = useState(""),
    [applied, setApplied] = useState({ start, end, business: "" }),
    [campaignOffset, setCampaignOffset] = useState(0),
    [merchantOffset, setMerchantOffset] = useState(0),
    [kind, setKind] = useState("daily");
  const params = new URLSearchParams({
    start_date: applied.start,
    end_date: applied.end,
    ...(applied.business ? { merchant_id: applied.business } : {}),
  });
  const query = useQuery({
    queryKey: [
      "analytics-report",
      auth.user?.id,
      applied,
      campaignOffset,
      merchantOffset,
    ],
    queryFn: () =>
      authorized<Report>(
        `/analytics/report?${params}&campaign_offset=${campaignOffset}&merchant_offset=${merchantOffset}`,
      ),
    retry: false,
    gcTime: 0,
  });
  const download = useMutation({
    mutationFn: () =>
      authorized<string>(`/analytics/export?${params}&kind=${kind}`),
    onSuccess: (csv) => {
      const url = URL.createObjectURL(
        new Blob([csv], { type: "text/csv;charset=utf-8" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `nearperk-${kind}-${applied.start}-${applied.end}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const data = query.data,
    dirty =
      start !== applied.start ||
      end !== applied.end ||
      business !== applied.business;
  function chooseBusiness(id: string) {
    setBusiness(id);
    setApplied({ ...applied, business: id });
    setCampaignOffset(0);
    setMerchantOffset(0);
    download.reset();
  }
  return (
    <>
      <header className="header">
        <Link className="brand" to={homePaths[role]}>
          ✳ nearperk.
        </Link>
        <Link to={homePaths[role]}>Back to dashboard</Link>
      </header>
      <main className="container workspace-shell analytics">
        <h1>Analytics and reports</h1>
        <form
          className="account-panel report-filters"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied({ start, end, business });
            setCampaignOffset(0);
            setMerchantOffset(0);
            download.reset();
          }}
        >
          <label>
            Start date
            <input
              type="date"
              required
              min="2000-01-01"
              max={today}
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            End date
            <input
              type="date"
              required
              min={start}
              max={today}
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          {role !== "MERCHANT" && (
            <p>
              Business: {business ? "Selected business" : "All businesses"}.
              Select a business name in the merchant report to filter.{" "}
              {business && (
                <button type="button" onClick={() => chooseBusiness("")}>
                  Show all businesses
                </button>
              )}
            </p>
          )}
          <button className="button">Apply dates</button>
          <p>
            Asia/Kolkata · 1–366 calendar days, inclusive. Today is a partial
            day.
          </p>
        </form>
        {dirty && (
          <p role="status">
            Apply your changes to update the report and exports.
          </p>
        )}
        <button
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          Refresh report
        </button>
        <QueryState
          pending={query.isPending}
          error={query.error}
          retry={query.refetch}
        />
        {data && !query.isError && (
          <>
            <p>
              Reporting {data.start_date} – {data.end_date} · {data.timezone}.
              As of {new Date(data.as_of).toLocaleString()}.
            </p>
            <section className="account-panel">
              <h2>Claims and engagement</h2>
              <dl className="report-metrics">
                {Object.entries(data.summary).map(([k, v]) => (
                  <div key={k}>
                    <dt>
                      {(
                        {
                          recorded_purchase_amount:
                            "Recorded purchase value (not verified revenue)",
                          coupon_benefit_amount: "Recorded coupon benefit",
                          dau: "Engaged shoppers on end date",
                          mau: "Engaged shoppers in 30 days ending on end date",
                          repeat_claimants: "Shoppers with multiple claims",
                        } as Record<string, string>
                      )[k] ||
                        labels[k] ||
                        k}
                    </dt>
                    <dd>{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
              <p>
                Conversion counts coupons claimed in this period and redeemed by
                its end. Redemptions during the period may include older claims.
                A dash means there is no denominator.
              </p>
              <p>
                Engagement counts signed-in shoppers who viewed tracked content,
                claimed or redeemed. Guests and logins alone are not counted.
                Browser-reported views/clicks are deduplicated per shopper,
                target and 30-minute bucket; they are not billing evidence.
              </p>
            </section>
            <section className="account-panel">
              <h2>Merchant retention</h2>
              <p>
                {data.retention.retained_merchants} retained of{" "}
                {data.retention.previous_active_merchants} previously active ·{" "}
                {data.retention.rate ?? "—"}%
              </p>
              <p>
                Compared with {data.retention.previous_start_date} –{" "}
                {data.retention.previous_end_date}. Active means at least one
                claim or redemption. Current-day comparisons are partial.
              </p>
            </section>
            <section className="account-panel">
              <h2>Daily activity</h2>
              <Table
                rows={data.daily}
                columns={["date", "claims", "redemptions", "engaged_shoppers"]}
              />
            </section>
            <section className="account-panel">
              <h2>Event analytics</h2>
              <Table rows={data.events} columns={["kind", "count"]} />
            </section>
            <section className="account-panel">
              <h2>Campaign analytics</h2>
              <Table
                rows={data.campaigns.items}
                columns={[
                  "id",
                  "title",
                  "status",
                  "claims",
                  "redemptions",
                  "cohort_redeemed",
                  "cohort_rate",
                ]}
              />
              <Pages
                offset={campaignOffset}
                next={data.campaigns.next_offset}
                onChange={setCampaignOffset}
              />
            </section>
            <section className="account-panel">
              <h2>Merchant report</h2>
              <Table
                rows={data.merchants.items}
                chooseBusiness={
                  role !== "MERCHANT" ? chooseBusiness : undefined
                }
                columns={[
                  "id",
                  "business_name",
                  "status",
                  "claims",
                  "redemptions",
                ]}
              />
              <Pages
                offset={merchantOffset}
                next={data.merchants.next_offset}
                onChange={setMerchantOffset}
              />
            </section>
            {data.revenue && (
              <section className="account-panel">
                <h2>Platform payment movement</h2>
                <p>
                  Sandbox rows are simulated and are not real revenue.
                  Currencies are never combined. Amounts are integer minor units
                  (100 = 1 currency unit for currently supported currencies).
                  Net movement is confirmed receipts minus refunds in this
                  period; it is not recognized accounting revenue. Ad and
                  pay-per-redemption billing are not implemented.
                </p>
                <Table
                  rows={data.revenue}
                  columns={[
                    "provider",
                    "currency",
                    "gross_minor",
                    "refund_minor",
                    "net_minor",
                    "payments",
                  ]}
                />
              </section>
            )}
            <section className="account-panel">
              <h2>Export CSV</h2>
              <p>
                Exports include all matching rows up to 10,000, independent of
                the displayed page. Larger exports are rejected; filter to a
                business. Files contain aggregates, not shopper identities or
                coupon codes.
              </p>
              <label>
                Export report
                <select
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value);
                    download.reset();
                  }}
                >
                  {[
                    "daily",
                    "campaigns",
                    "merchants",
                    "events",
                    ...(role === "SUPER_ADMIN" ? ["revenue"] : []),
                  ].map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </select>
              </label>
              <button
                disabled={download.isPending || query.isFetching || dirty}
                onClick={() => download.mutate()}
              >
                Download CSV
              </button>
              <Feedback error={download.error} />
            </section>
          </>
        )}
      </main>
    </>
  );
}
