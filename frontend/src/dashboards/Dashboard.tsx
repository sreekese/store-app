import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import type { Role } from "../auth/types";
interface Metrics {
  scope: string;
  generated_at: string;
  timezone: string;
  days: number;
  start_date: string;
  end_date: string;
  totals: Record<string, number | string | null>;
  daily: { date: string; claims?: number; redemptions: number }[];
  top_offers: { offer_id: string; title: string; claims: number }[];
}
const labels: Record<string, string> = {
  users: "Registered accounts",
  merchants: "Merchant businesses",
  stores: "Branches",
  offers: "Offers",
  campaigns: "Coupon campaigns",
  claims: "Coupons claimed",
  active_coupons: "Unspent, unexpired coupons",
  redemptions: "Coupons redeemed",
  redemption_rate: "Lifetime redemption rate",
  assigned_branches: "Assigned branches",
  recorded_purchase_amount: "Recorded eligible purchases",
  coupon_benefit_amount: "Recorded coupon benefits",
};
export default function Dashboard({ role }: { role: Role }) {
  const [days, setDays] = useState(30);
  const scope =
    role === "MERCHANT"
      ? "merchant"
      : role === "MERCHANT_STAFF"
        ? "staff"
        : "platform";
  const query = useQuery({
    queryKey: ["dashboard", scope, days],
    queryFn: () => authorized<Metrics>(`/dashboards/${scope}?days=${days}`),
    retry: false,
    refetchInterval: 60000,
    gcTime: 0,
  });
  const data = query.data;
  const max = Math.max(
    1,
    ...(data?.daily.flatMap((d) => [d.claims ?? 0, d.redemptions]) ?? []),
  );
  return (
    <section
      className="account-panel dashboard"
      aria-label="Activity dashboard"
    >
      <p className="eyebrow">ACTIVITY OVERVIEW</p>
      <h2>
        {scope === "platform"
          ? "Platform overview"
          : scope === "staff"
            ? "Your counter activity"
            : "Your business overview"}
      </h2>
      <p>
        {scope === "staff"
          ? "Your own redemptions at currently assigned branches only."
          : scope === "merchant"
            ? "Your business only, across all branches."
            : "Platform-wide totals across all account and business statuses."}
      </p>
      <div className="form-actions">
        <label>
          Chart period
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
        <button
          className="text-button"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Refresh metrics
        </button>
      </div>
      {query.isPending ? (
        <p role="status">Loading activity metrics…</p>
      ) : query.isError ? (
        <div role="alert">
          <p>{query.error.message}</p>
          <button onClick={() => void query.refetch()}>Retry metrics</button>
        </div>
      ) : (
        data && (
          <>
            <h3>Lifetime totals</h3>
            <dl className="dashboard-metrics">
              {Object.entries(data.totals).map(([key, value]) => (
                <div key={key}>
                  <dt>{labels[key] ?? key}</dt>
                  <dd>
                    {value === null
                      ? "—"
                      : key.endsWith("_amount")
                        ? `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : key === "redemption_rate"
                          ? `${value}%`
                          : Number(value).toLocaleString("en-IN")}
                  </dd>
                </div>
              ))}
            </dl>
            {scope !== "staff" && (
              <p className="muted">
                Unspent, unexpired coupons are checked now; branch availability
                and saved terms still apply. Redemption rate is lifetime
                redemptions divided by all lifetime claims, including expired
                and cancelled claims. A dash means there are no claims.
              </p>
            )}
            <p>
              Purchase and benefit amounts are staff-entered coupon records, not
              verified revenue or payments.
            </p>
            <h3>Daily activity</h3>
            <p>
              {data.start_date} to {data.end_date} · {data.timezone} · today is
              partial
            </p>
            <p>
              {scope !== "staff" && "Green: claims. "}Gold: redemptions.
              Redemptions are counted on their redemption date.
            </p>
            {!data.daily.some((d) => d.claims || d.redemptions) && (
              <p>No activity in this period.</p>
            )}
            <div className="dashboard-chart" aria-hidden="true">
              {data.daily.map((d) => (
                <div
                  className="dashboard-day"
                  key={d.date}
                  title={`${d.date}: ${d.claims ?? 0} claims, ${d.redemptions} redemptions`}
                >
                  {scope !== "staff" && (
                    <span
                      className="claims-bar"
                      style={{ height: `${((d.claims ?? 0) / max) * 100}%` }}
                    />
                  )}
                  <span
                    className="redemptions-bar"
                    style={{ height: `${(d.redemptions / max) * 100}%` }}
                  />
                </div>
              ))}
            </div>
            <details>
              <summary>View daily counts</summary>
              <div className="dashboard-table">
                <table>
                  <caption>Daily activity in {data.timezone}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      {scope !== "staff" && <th scope="col">Claims</th>}
                      <th scope="col">Redemptions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.daily.map((d) => (
                      <tr key={d.date}>
                        <th scope="row">{d.date}</th>
                        {scope !== "staff" && <td>{d.claims}</td>}
                        <td>{d.redemptions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            {scope !== "staff" && (
              <>
                <h3>Top offers by claims in this period</h3>
                <p>
                  Up to five offers, across their campaigns. Titles reflect
                  current offer names.
                </p>
                {data.top_offers.length ? (
                  <ol className="dashboard-top">
                    {data.top_offers.map((o) => (
                      <li key={o.offer_id}>
                        <span>{o.title}</span>
                        <strong>{o.claims} claims</strong>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>No claimed offers in this period.</p>
                )}
              </>
            )}
            <p className="muted">
              Updated {new Date(data.generated_at).toLocaleString()} · refreshes
              every minute
            </p>
          </>
        )
      )}
    </section>
  );
}
