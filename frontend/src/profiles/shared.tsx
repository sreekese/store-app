import type { InputHTMLAttributes } from "react";
import { authorized } from "../auth/client";
export interface Merchant {
  id: string;
  business_name: string;
  category: string;
  description: string;
  website: string;
  logo_url: string;
  cover_image_url: string;
  contact_email: string;
  phone: string;
  status: string;
  review_note: string;
  revision: number;
  updated_at: string;
}
export interface Hours {
  day_of_week: number;
  is_closed: boolean;
  open_time: string | null;
  close_time: string | null;
  closes_next_day: boolean;
}
export interface Store {
  id: string;
  merchant_id: string;
  name: string;
  address: string;
  city: string;
  area: string;
  state: string;
  country: string;
  postal_code: string;
  phone: string;
  timezone: string;
  latitude: number | null;
  longitude: number | null;
  status: "ACTIVE" | "INACTIVE";
  hours: Hours[];
  revision: number;
  updated_at: string;
}
export interface StaffMember {
  revision: number;
  account_active: boolean;
  id: string;
  email: string;
  display_name: string;
  store_ids: string[];
}
export interface Invitation {
  status: "PENDING" | "ACCEPTED" | "CANCELLED" | "EXPIRED";
  id: string;
  email: string;
  store_ids: string[];
  expires_at: string;
  closed_at: string | null;
  accepted_at: string | null;
}
export function mutate<T>(path: string, data: unknown, method = "PUT") {
  return authorized<T>(path, {
    method,
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}
export function Field({
  label,
  ...props
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label>
      {label}
      <input {...props} />
    </label>
  );
}
export function Feedback({
  error,
  success,
}: {
  error?: Error | null;
  success?: string;
}) {
  return (
    <>
      {error && (
        <p className="form-error" role="alert">
          {error.message}
        </p>
      )}
      {success && (
        <p className="save-success" role="status">
          {success}
        </p>
      )}
    </>
  );
}
export function QueryState({
  pending,
  error,
  retry,
}: {
  pending: boolean;
  error: Error | null;
  retry: () => unknown;
}) {
  return pending ? (
    <p role="status">Loading…</p>
  ) : error ? (
    <div className="notice">
      <p role="alert">{error.message}</p>
      <button className="text-button" onClick={() => void retry()}>
        Try again
      </button>
    </div>
  ) : null;
}
export function StoreChoices({
  stores,
  selected,
  onChange,
  disabled = false,
}: {
  stores: Store[];
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset disabled={disabled} className="store-choices">
      <legend>Assigned stores</legend>
      {stores.map((store) => (
        <label key={store.id}>
          <input
            type="checkbox"
            disabled={
              store.status === "INACTIVE" && !selected.includes(store.id)
            }
            checked={selected.includes(store.id)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...selected, store.id]
                  : selected.filter((id) => id !== store.id),
              )
            }
          />
          {store.name} · {store.city}
          {store.status === "INACTIVE" ? " (inactive)" : ""}
        </label>
      ))}
    </fieldset>
  );
}
