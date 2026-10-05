import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import {
  Feedback,
  Field,
  mutate,
  QueryState,
  type Hours,
  type Store,
} from "../profiles/shared";
import { useDeviceLocation } from "./useDeviceLocation";
export const days = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const defaultWeek = (): Hours[] =>
  days.map((_, day_of_week) => ({
    day_of_week,
    is_closed: false,
    open_time: "09:00",
    close_time: "18:00",
    closes_next_day: false,
  }));
function BranchForm({
  store,
  suspended,
  saved,
  cancel,
}: {
  store: Store | null;
  suspended: boolean;
  saved: (message: string) => void;
  cancel: () => void;
}) {
  const [values, setValues] = useState({
    name: store?.name || "",
    address: store?.address || "",
    city: store?.city || "",
    area: store?.area || "",
    state: store?.state || "",
    country: store?.country || "IN",
    postal_code: store?.postal_code || "",
    phone: store?.phone || "",
    timezone: store?.timezone || "Asia/Kolkata",
    status: store?.status || "ACTIVE",
    latitude: store?.latitude == null ? "" : String(store.latitude),
    longitude: store?.longitude == null ? "" : String(store.longitude),
  });
  const [hours, setHours] = useState<Hours[]>(
    store?.hours?.length
      ? [...store.hours].sort((a, b) => a.day_of_week - b.day_of_week)
      : defaultWeek(),
  );
  const [hasHours, setHasHours] = useState(!!store?.hours?.length),
    client = useQueryClient(),
    gps = useDeviceLocation();
  const save = useMutation({
    mutationFn: () =>
      mutate<Store>(
        store ? `/merchant/stores/${store.id}` : "/merchant/stores",
        {
          ...values,
          latitude: values.latitude === "" ? null : Number(values.latitude),
          longitude: values.longitude === "" ? null : Number(values.longitude),
          hours: hasHours ? hours : [],
          ...(store ? { revision: store.revision } : {}),
        },
        store ? "PUT" : "POST",
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["merchant-stores"] });
      saved(store ? "Branch updated." : "Branch added.");
    },
  });
  function hourChange(index: number, update: Partial<Hours>) {
    setHours(
      hours.map((hour, i) => (i === index ? { ...hour, ...update } : hour)),
    );
  }
  return (
    <form
      className="auth-form profile-form branch-form"
      onSubmit={(e) => {
        e.preventDefault();
        gps.cancel();
        save.mutate();
      }}
    >
      <h3>{store ? `Edit ${store.name}` : "Add a branch"}</h3>
      <fieldset disabled={suspended || save.isPending}>
        <div className="form-grid">
          <Field
            label="Branch name"
            required
            minLength={2}
            maxLength={150}
            value={values.name}
            onChange={(e) => setValues({ ...values, name: e.target.value })}
          />
          <Field
            label="Branch city"
            required
            minLength={2}
            maxLength={100}
            value={values.city}
            onChange={(e) => setValues({ ...values, city: e.target.value })}
          />
          <Field
            label="Area"
            maxLength={100}
            value={values.area}
            onChange={(e) => setValues({ ...values, area: e.target.value })}
          />
          <Field
            label="State / region"
            maxLength={100}
            value={values.state}
            onChange={(e) => setValues({ ...values, state: e.target.value })}
          />
          <Field
            label="Country code"
            required
            minLength={2}
            maxLength={2}
            pattern="[A-Z]{2}"
            value={values.country}
            onChange={(e) =>
              setValues({ ...values, country: e.target.value.toUpperCase() })
            }
          />
          <Field
            label="Postal code"
            maxLength={20}
            value={values.postal_code}
            onChange={(e) =>
              setValues({ ...values, postal_code: e.target.value })
            }
          />
        </div>
        <Field
          label="Branch address"
          required
          minLength={3}
          maxLength={500}
          value={values.address}
          onChange={(e) => setValues({ ...values, address: e.target.value })}
        />
        <Field
          label="Branch phone"
          type="tel"
          maxLength={30}
          value={values.phone}
          onChange={(e) => setValues({ ...values, phone: e.target.value })}
        />
        <div className="location-fields">
          <h4>Store location</h4>
          <p>
            Enter the branch’s map coordinates. Both are needed for nearby
            discovery.
          </p>
          <div className="form-grid">
            <Field
              label="Latitude"
              type="number"
              step="any"
              min={-90}
              max={90}
              required={values.longitude !== ""}
              value={values.latitude}
              onChange={(e) => {
                gps.cancel();
                setValues({ ...values, latitude: e.target.value });
              }}
            />
            <Field
              label="Longitude"
              type="number"
              step="any"
              min={-180}
              max={180}
              required={values.latitude !== ""}
              value={values.longitude}
              onChange={(e) => {
                gps.cancel();
                setValues({ ...values, longitude: e.target.value });
              }}
            />
          </div>
          <button
            type="button"
            className="text-button"
            disabled={gps.pending}
            onClick={() =>
              gps.locate((point) =>
                setValues((previous) => ({
                  ...previous,
                  latitude: String(point.latitude),
                  longitude: String(point.longitude),
                })),
              )
            }
          >
            {gps.pending ? "Locating…" : "Use this device’s location"}
          </button>
          <small>Use this only while you are at the branch.</small>
          {gps.error && (
            <p role="alert" className="form-error">
              {gps.error}
            </p>
          )}
        </div>
        <label>
          Branch status
          <select
            value={values.status}
            onChange={(e) =>
              setValues({
                ...values,
                status: e.target.value as Store["status"],
              })
            }
          >
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>
        </label>
        <small>
          Inactive branches are hidden from discovery and staff access. Existing
          assignments are retained for reactivation.
        </small>
        <div className="hours-editor">
          <h4>Opening hours</h4>
          <Field
            label="Store timezone"
            required
            maxLength={100}
            placeholder="Asia/Kolkata"
            value={values.timezone}
            onChange={(e) => setValues({ ...values, timezone: e.target.value })}
          />
          <label className="check-label">
            <input
              type="checkbox"
              checked={hasHours}
              onChange={(e) => setHasHours(e.target.checked)}
            />
            Publish weekly hours
          </label>
          <small>
            Times are local to the store. Overnight periods close the following
            day. Unpublished hours appear as “Hours not provided”.
          </small>
          {hasHours &&
            hours.map((hour, index) => (
              <fieldset className="hours-row" key={hour.day_of_week}>
                <legend>{days[hour.day_of_week]}</legend>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={hour.is_closed}
                    onChange={(e) =>
                      hourChange(
                        index,
                        e.target.checked
                          ? {
                              is_closed: true,
                              open_time: null,
                              close_time: null,
                              closes_next_day: false,
                            }
                          : {
                              is_closed: false,
                              open_time: "09:00",
                              close_time: "18:00",
                            },
                      )
                    }
                  />
                  Closed {days[hour.day_of_week]}
                </label>
                {!hour.is_closed && (
                  <div className="form-grid">
                    <Field
                      label={`${days[hour.day_of_week]} opens`}
                      type="time"
                      required
                      value={hour.open_time || ""}
                      onChange={(e) =>
                        hourChange(index, { open_time: e.target.value })
                      }
                    />
                    <Field
                      label={`${days[hour.day_of_week]} closes`}
                      type="time"
                      required
                      value={hour.close_time || ""}
                      onChange={(e) =>
                        hourChange(index, { close_time: e.target.value })
                      }
                    />
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={hour.closes_next_day}
                        onChange={(e) =>
                          hourChange(index, {
                            closes_next_day: e.target.checked,
                          })
                        }
                      />
                      Closes next day ({days[hour.day_of_week]})
                    </label>
                  </div>
                )}
              </fieldset>
            ))}
        </div>
        <Feedback error={save.error} />
        <div className="action-row">
          <button className="button" disabled={save.isPending}>
            {save.isPending ? "Saving…" : store ? "Save branch" : "Add branch"}
          </button>
          {store && (
            <button
              type="button"
              className="text-button"
              onClick={() => {
                gps.cancel();
                cancel();
              }}
            >
              Cancel editing
            </button>
          )}
        </div>
      </fieldset>
    </form>
  );
}
export default function BranchManager({ suspended }: { suspended: boolean }) {
  const query = useQuery({
    queryKey: ["merchant-stores"],
    queryFn: () => authorized<Store[]>("/merchant/stores"),
    retry: false,
  });
  const [editing, setEditing] = useState<Store | null>(null),
    [notice, setNotice] = useState(""),
    [formVersion, setFormVersion] = useState(0);
  return (
    <section className="account-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Your locations</p>
          <h2>Branches</h2>
        </div>
        <button
          className="text-button"
          disabled={query.isFetching}
          onClick={() => {
            setEditing(null);
            setFormVersion((v) => v + 1);
            void query.refetch();
          }}
        >
          Reload branches
        </button>
      </div>
      <p>
        Manage where people find you, when you’re open, and which branches are
        active.
      </p>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      <Feedback success={notice} />
      {query.data?.length === 0 && (
        <p className="empty-state">
          No branches yet. Add your first location below.
        </p>
      )}
      <div className="branch-grid">
        {query.data?.map((store) => (
          <article className="branch-card" key={store.id}>
            <div className="section-heading">
              <h3>{store.name}</h3>
              <span className="badge">{store.status || "ACTIVE"}</span>
            </div>
            <p>{store.address}</p>
            <p>{[store.area, store.city].filter(Boolean).join(", ")}</p>
            <p>
              {store.latitude == null
                ? "Add coordinates to appear in nearby discovery."
                : `${store.latitude}, ${store.longitude}`}
            </p>
            <p>
              {store.hours?.length
                ? `Weekly hours · ${store.timezone}`
                : "Hours not provided"}
            </p>
            <button
              className="text-button"
              disabled={suspended}
              onClick={() => {
                setNotice("");
                setEditing(store);
              }}
            >
              Edit branch: {store.name}
            </button>
          </article>
        ))}
      </div>
      <BranchForm
        key={(editing?.id || "new") + ":" + formVersion}
        store={editing}
        suspended={suspended}
        cancel={() => setEditing(null)}
        saved={(message) => {
          setNotice(message);
          setEditing(null);
          setFormVersion((v) => v + 1);
        }}
      />
    </section>
  );
}
