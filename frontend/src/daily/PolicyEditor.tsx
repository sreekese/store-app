import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Field, Feedback, QueryState } from "../profiles/shared";
interface Policy {
  next_reset?: string;
  version: number;
  allowance: number;
  period: string;
  timezone: string;
  default_radius_km: number;
  max_radius_km: number;
  effective_at: string;
}
interface History {
  policies: Policy[];
  audit: {
    id: string;
    action: string;
    at: string;
    actor_id: string;
    detail: unknown;
  }[];
}
interface Preview {
  affected_users: number;
  effective_at: string;
  next_reset: string;
  message: string;
  pending_version: number | null;
}
export default function PolicyEditor() {
  const client = useQueryClient(),
    [offset, setOffset] = useState(0),
    [form, setForm] = useState<Policy | null>(null),
    [confirmed, setConfirmed] = useState(false);
  const current = useQuery({
    queryKey: ["coupon-policy"],
    queryFn: () => authorized<Policy>("/daily/policy"),
  });
  const history = useQuery({
    queryKey: ["policy-history", offset],
    queryFn: () =>
      authorized<History>(`/daily/policy/history?offset=${offset}`),
  });
  const payload = () => ({
    allowance: form!.allowance,
    period: form!.period,
    timezone: form!.timezone,
    default_radius_km: form!.default_radius_km,
    max_radius_km: form!.max_radius_km,
    effective_at: form!.effective_at,
    current_version: form!.version,
  });
  const preview = useMutation({
    mutationFn: () =>
      authorized<Preview>("/daily/policy/preview", {
        method: "POST",
        body: JSON.stringify(payload()),
      }),
  });
  const save = useMutation({
    mutationFn: () =>
      authorized("/daily/policy/schedule", {
        method: "POST",
        body: JSON.stringify(payload()),
      }),
    onSuccess: () => {
      setForm(null);
      preview.reset();
      void client.invalidateQueries({ queryKey: ["policy-history"] });
    },
  });
  const cancel = useMutation({
    mutationFn: (version: number) =>
      authorized(`/daily/policy/${version}`, { method: "DELETE" }),
    onSuccess: () => {
      void history.refetch();
      preview.reset();
      setConfirmed(false);
    },
  });
  const update = (key: keyof Policy, value: string | number) => {
    setForm({ ...form!, [key]: value });
    preview.reset();
    save.reset();
    setConfirmed(false);
  };
  return (
    <section className="account-panel">
      <h2>Coupon allowance policy</h2>
      <QueryState
        pending={current.isPending}
        error={current.error}
        retry={current.refetch}
      />
      {current.data && !current.isError && (
        <>
          <p>
            Current: {current.data.allowance} per{" "}
            {current.data.period.toLowerCase()} period · {current.data.timezone}{" "}
            · radius {current.data.default_radius_km}–
            {current.data.max_radius_km} km.
          </p>
          <button
            onClick={() => {
              setForm({
                ...current.data!,
                effective_at: current.data!.next_reset || "",
              });
              preview.reset();
              setConfirmed(false);
            }}
          >
            Prepare policy change
          </button>
        </>
      )}
      {form && (
        <form
          className="profile-form"
          onSubmit={(e) => {
            e.preventDefault();
            preview.mutate();
          }}
        >
          <fieldset disabled={preview.isPending || save.isPending}>
            <Field
              label="Claims per period"
              type="number"
              min="1"
              max="100"
              required
              value={form.allowance}
              onChange={(e) => update("allowance", Number(e.target.value))}
            />
            <label>
              Allowance period
              <select
                value={form.period}
                onChange={(e) => update("period", e.target.value)}
              >
                <option value="DAILY">Daily</option>
                <option value="WEEKLY">Weekly (Monday reset)</option>
              </select>
            </label>
            <Field
              label="Reset timezone (IANA)"
              required
              value={form.timezone}
              onChange={(e) => update("timezone", e.target.value)}
            />
            <Field
              label="Default radius (km)"
              type="number"
              min="0.1"
              max="100"
              step="0.1"
              value={form.default_radius_km}
              onChange={(e) =>
                update("default_radius_km", Number(e.target.value))
              }
            />
            <Field
              label="Maximum radius (km)"
              type="number"
              min="0.1"
              max="100"
              step="0.1"
              value={form.max_radius_km}
              onChange={(e) => update("max_radius_km", Number(e.target.value))}
            />
            <Field
              label="Activation timestamp with timezone"
              placeholder="2026-10-01T00:00:00+05:30"
              required
              value={form.effective_at}
              onChange={(e) => update("effective_at", e.target.value)}
            />
            <p>
              Use a future reset boundary of the current policy. Weekly periods
              start Monday; daily periods start at midnight.
            </p>
            <button>Preview impact</button>
          </fieldset>
        </form>
      )}
      <Feedback
        error={preview.error || save.error || cancel.error}
        success={
          save.isSuccess
            ? "Policy scheduled."
            : cancel.isSuccess
              ? "Pending policy cancelled."
              : undefined
        }
      />
      {preview.data && form && (
        <div className="notice">
          <p>{preview.data.message}</p>
          <p>
            Affected active shoppers: {preview.data.affected_users}. Activation:{" "}
            {new Date(preview.data.effective_at).toLocaleString()}. Next current
            reset: {new Date(preview.data.next_reset).toLocaleString()}.
          </p>
          {preview.data.pending_version ? (
            <p>
              Cancel pending policy {preview.data.pending_version} before
              scheduling another.
            </p>
          ) : (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />{" "}
                I reviewed the impact and activation time.
              </label>
              <button
                disabled={!confirmed || save.isPending}
                onClick={() => save.mutate()}
              >
                Confirm scheduled policy
              </button>
            </>
          )}
        </div>
      )}
      <h3>Policy history</h3>
      <QueryState
        pending={history.isPending}
        error={history.error}
        retry={history.refetch}
      />
      {history.data && !history.isError && (
        <>
          {history.data.policies.map((p) => (
            <article key={p.version}>
              <p>
                Version {p.version}: {p.allowance} per {p.period.toLowerCase()}{" "}
                · {p.timezone} · effective{" "}
                {new Date(p.effective_at).toLocaleString()}
              </p>
              {new Date(p.effective_at) > new Date() && (
                <button
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate(p.version)}
                >
                  Cancel pending version {p.version}
                </button>
              )}
            </article>
          ))}
          <details>
            <summary>Policy audit trail</summary>
            {history.data.audit.map((a) => (
              <p key={a.id}>
                {a.action} · {new Date(a.at).toLocaleString()} · actor{" "}
                {a.actor_id || "removed account"}
                <br />
                {JSON.stringify(a.detail)}
              </p>
            ))}
          </details>
          <button
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 25))}
          >
            Previous history
          </button>
          <button
            disabled={
              history.data.policies.length < 25 &&
              history.data.audit.length < 25
            }
            onClick={() => setOffset(offset + 25)}
          >
            More history
          </button>
        </>
      )}
    </section>
  );
}
