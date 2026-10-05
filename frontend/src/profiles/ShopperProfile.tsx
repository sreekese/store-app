import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { authorized } from "../auth/client";
import type { AuthResult } from "../auth/types";
import { Field, Feedback, mutate, QueryState } from "./shared";
interface Profile {
  email: string;
  display_name: string;
  phone: string;
  city: string;
  area: string;
  postal_code: string;
  location_preference: "GPS" | "MANUAL";
}
function ProfileForm({ profile }: { profile: Profile }) {
  const [values, setValues] = useState(profile),
    client = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      const { email: _email, ...data } = values;
      void _email;
      return mutate<Profile>("/profile", data);
    },
    onSuccess: (data) => {
      client.setQueryData(["profile"], data);
      client.setQueryData<AuthResult>(["auth-session"], (previous) =>
        previous
          ? {
              ...previous,
              user: { ...previous.user, display_name: data.display_name },
            }
          : previous,
      );
    },
  });
  return (
    <form
      className="auth-form profile-form"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Field
        label="Display name"
        required
        maxLength={100}
        value={values.display_name}
        onChange={(e) => setValues({ ...values, display_name: e.target.value })}
      />
      <Field label="Account email" type="email" value={values.email} readOnly />
      <small>Your sign-in email is fixed for this release.</small>
      <Field
        label="Phone"
        type="tel"
        maxLength={30}
        value={values.phone}
        onChange={(e) => setValues({ ...values, phone: e.target.value })}
      />
      <div className="form-grid">
        <Field
          label="City"
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
          label="Postal code"
          maxLength={20}
          value={values.postal_code}
          onChange={(e) =>
            setValues({ ...values, postal_code: e.target.value })
          }
        />
      </div>
      <label>
        Preferred location method
        <select
          value={values.location_preference}
          onChange={(e) =>
            setValues({
              ...values,
              location_preference: e.target
                .value as Profile["location_preference"],
            })
          }
        >
          <option value="MANUAL">Enter a place</option>
          <option value="GPS">Use my location</option>
        </select>
      </label>
      <small>
        This saves your preference. Use the discovery controls above to choose
        your search location.
      </small>
      <Feedback
        error={save.error}
        success={save.isSuccess ? "Profile saved." : undefined}
      />
      <button className="button" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save profile"}
      </button>
    </form>
  );
}
export default function ShopperProfile() {
  const query = useQuery({
    queryKey: ["profile"],
    queryFn: () => authorized<Profile>("/profile"),
    retry: false,
  });
  return (
    <section className="account-panel">
      <p className="eyebrow">A little about you</p>
      <h2>Your profile</h2>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && <ProfileForm profile={query.data} />}
    </section>
  );
}
