import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Field, Feedback, QueryState } from "../profiles/shared";
interface Pick {
  campaign_id: string | null;
  revision: number;
  actor_id: string;
  updated_at: string;
}
export default function DailyPicks({
  superadmin = false,
}: {
  superadmin?: boolean;
}) {
  const [store, setStore] = useState(""),
    [date, setDate] = useState(""),
    [campaign, setCampaign] = useState(""),
    [offset, setOffset] = useState(0),
    [cOffset, setCOffset] = useState(0),
    [hOffset, setHOffset] = useState(0),
    client = useQueryClient();
  const source = superadmin ? "SUPER_ADMIN" : "MERCHANT";
  const stores = useQuery({
    queryKey: ["daily-stores", offset],
    queryFn: () =>
      authorized<{ id: string; name: string }[]>(
        `/daily/stores?offset=${offset}`,
      ),
  });
  const policy = useQuery({
    queryKey: ["coupon-policy"],
    queryFn: () => authorized<{ timezone: string }>("/daily/policy"),
  });
  const path = `/daily/stores/${store}/picks/${date}`;
  const picks = useQuery({
    queryKey: ["daily-pick", store, date],
    queryFn: () => authorized<Record<string, Pick>>(path),
    enabled: !!store && !!date,
    retry: false,
  });
  const candidates = useQuery({
    queryKey: ["daily-candidates", store, date, cOffset],
    queryFn: () =>
      authorized<{ id: string; title: string; available: number }[]>(
        `/daily/stores/${store}/candidates?business_date=${date}&offset=${cOffset}`,
      ),
    enabled: !!store && !!date,
    retry: false,
  });
  const history = useQuery({
    queryKey: ["daily-history", store, hOffset],
    queryFn: () =>
      authorized<{ id: string; action: string; at: string; detail: unknown }[]>(
        `/daily/stores/${store}/history?offset=${hOffset}`,
      ),
    enabled: !!store,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (remove: boolean) =>
      authorized(
        path + (remove ? `?revision=${picks.data?.[source]?.revision}` : ""),
        {
          method: remove ? "DELETE" : "PUT",
          body: remove
            ? undefined
            : JSON.stringify({
                campaign_id: campaign || null,
                revision: picks.data?.[source]?.revision || 0,
              }),
        },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["daily-pick"] });
      void client.invalidateQueries({ queryKey: ["daily-history"] });
      void client.invalidateQueries({ queryKey: ["daily-coupons"] });
    },
    onError: () => {
      void picks.refetch();
    },
  });
  return (
    <section className="account-panel">
      <h2>{superadmin ? "Store daily overrides" : "Store daily picks"}</h2>
      <p>
        One selection per store and business date (
        {policy.data?.timezone || "platform timezone"}). Superadmin overrides
        take precedence, including no selection. Removing an override restores
        the merchant pick. Selection never reserves stock.
      </p>
      <QueryState
        pending={stores.isPending}
        error={stores.error}
        retry={stores.refetch}
      />
      <label>
        Daily pick branch
        <select
          value={store}
          onChange={(e) => {
            setStore(e.target.value);
            setCampaign("");
            setCOffset(0);
            setHOffset(0);
            save.reset();
          }}
        >
          <option value="">Choose branch</option>
          {stores.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <button
        disabled={!offset}
        onClick={() => setOffset(Math.max(0, offset - 25))}
      >
        Previous branches
      </button>
      <button
        disabled={!stores.data || stores.data.length < 25}
        onClick={() => setOffset(offset + 25)}
      >
        More branches
      </button>
      <Field
        label="Business date"
        type="date"
        value={date}
        onChange={(e) => {
          setDate(e.target.value);
          setCampaign("");
          setCOffset(0);
          save.reset();
        }}
      />
      {store && date && (
        <>
          <QueryState
            pending={picks.isPending || candidates.isPending}
            error={picks.error || candidates.error}
            retry={() => {
              void picks.refetch();
              void candidates.refetch();
            }}
          />
          {picks.data && !picks.isError && (
            <p>
              Merchant pick: {picks.data.MERCHANT?.campaign_id || "none"}.
              Override:{" "}
              {picks.data.SUPER_ADMIN
                ? picks.data.SUPER_ADMIN.campaign_id ||
                  "explicitly no selection"
                : "not set"}
              .
            </p>
          )}
          <label>
            Eligible campaign
            <select
              value={campaign}
              onChange={(e) => setCampaign(e.target.value)}
            >
              <option value="">No selection</option>
              {candidates.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} · {c.available} available
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={!cOffset}
            onClick={() => setCOffset(Math.max(0, cOffset - 25))}
          >
            Previous candidates
          </button>
          <button
            disabled={!candidates.data || candidates.data.length < 25}
            onClick={() => setCOffset(cOffset + 25)}
          >
            More candidates
          </button>
          <button
            disabled={
              save.isPending ||
              picks.isPending ||
              picks.isError ||
              candidates.isError
            }
            onClick={() => save.mutate(false)}
          >
            Save {superadmin ? "override" : "daily pick"}
          </button>
          <button
            disabled={save.isPending || !picks.data?.[source] || picks.isError}
            onClick={() => save.mutate(true)}
          >
            Remove {superadmin ? "override" : "daily pick"}
          </button>
        </>
      )}
      <Feedback
        error={save.error}
        success={save.isSuccess ? "Daily selection updated." : undefined}
      />
      {store && (
        <details>
          <summary>Selection audit trail</summary>
          <QueryState
            pending={history.isPending}
            error={history.error}
            retry={history.refetch}
          />
          {!history.isError &&
            history.data?.map((a) => (
              <p key={a.id}>
                {a.action} · {new Date(a.at).toLocaleString()}
                <br />
                {JSON.stringify(a.detail)}
              </p>
            ))}
          <button
            disabled={!hOffset}
            onClick={() => setHOffset(Math.max(0, hOffset - 25))}
          >
            Previous changes
          </button>
          <button
            disabled={!history.data || history.data.length < 25}
            onClick={() => setHOffset(hOffset + 25)}
          >
            More changes
          </button>
        </details>
      )}
    </section>
  );
}
