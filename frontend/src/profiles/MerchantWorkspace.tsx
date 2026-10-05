import StaffManager from "./StaffManager";
import BranchManager from "../locations/BranchManager";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Field, Feedback, mutate, QueryState, type Merchant } from "./shared";
function BusinessForm({ profile }: { profile: Merchant | null }) {
  const client = useQueryClient();
  const [values, setValues] = useState({
    business_name: profile?.business_name || "",
    category: profile?.category || "",
    description: profile?.description || "",
    contact_email: profile?.contact_email || "",
    phone: profile?.phone || "",
    website: profile?.website || "",
    logo_url: profile?.logo_url || "",
    cover_image_url: profile?.cover_image_url || "",
  });
  const save = useMutation({
    mutationFn: () => mutate<Merchant>("/merchant/profile", values),
    onSuccess: (data) => {
      client.setQueryData(["merchant-profile"], data);
    },
  });
  return (
    <form
      className="auth-form profile-form"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="form-grid">
        <Field
          label="Business name"
          required
          minLength={2}
          maxLength={150}
          value={values.business_name}
          onChange={(e) =>
            setValues({ ...values, business_name: e.target.value })
          }
        />
        <Field
          label="Business category"
          placeholder="e.g. Café, grocery, salon"
          required
          minLength={2}
          maxLength={100}
          value={values.category}
          onChange={(e) => setValues({ ...values, category: e.target.value })}
        />
        <Field
          label="Business contact email"
          type="email"
          required
          value={values.contact_email}
          onChange={(e) =>
            setValues({ ...values, contact_email: e.target.value })
          }
        />
        <Field
          label="Business phone"
          type="tel"
          required
          minLength={5}
          maxLength={30}
          value={values.phone}
          onChange={(e) => setValues({ ...values, phone: e.target.value })}
        />
      </div>
      <label>
        About your business
        <textarea
          maxLength={2000}
          rows={4}
          value={values.description}
          onChange={(e) =>
            setValues({ ...values, description: e.target.value })
          }
        />
      </label>
      <details className="business-links">
        <summary>Website and brand images (optional)</summary>
        <div className="form-grid">
          <Field
            label="Business website"
            type="url"
            maxLength={2048}
            value={values.website}
            onChange={(e) => setValues({ ...values, website: e.target.value })}
          />
          <Field
            label="Logo image URL"
            type="url"
            maxLength={2048}
            value={values.logo_url}
            onChange={(e) => setValues({ ...values, logo_url: e.target.value })}
          />
          <Field
            label="Cover image URL"
            type="url"
            maxLength={2048}
            value={values.cover_image_url}
            onChange={(e) =>
              setValues({ ...values, cover_image_url: e.target.value })
            }
          />
        </div>
        <small>Use a public HTTPS link for each image.</small>
      </details>
      <p className="muted">
        Submitting changes sends your business for review. Staff access pauses
        until it is verified again.
      </p>
      <Feedback
        error={save.error}
        success={save.isSuccess ? "Business submitted for review." : undefined}
      />
      <button
        className="button"
        disabled={save.isPending || profile?.status === "SUSPENDED"}
      >
        {save.isPending ? "Submitting…" : "Submit for verification"}
      </button>
    </form>
  );
}
export default function MerchantWorkspace() {
  const profile = useQuery({
    queryKey: ["merchant-profile"],
    queryFn: () => authorized<Merchant | null>("/merchant/profile"),
    retry: false,
  });
  return (
    <>
      <section className="account-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Grow locally</p>
            <h2>Business profile</h2>
          </div>
          {profile.data && (
            <span className="badge">
              {profile.data.status.replaceAll("_", " ")}
            </span>
          )}
        </div>
        <QueryState
          pending={profile.isPending}
          error={profile.error}
          retry={profile.refetch}
        />
        {profile.data?.review_note && (
          <p className="notice">Review note: {profile.data.review_note}</p>
        )}
        {profile.isSuccess && <BusinessForm profile={profile.data} />}
      </section>
      {profile.data && !profile.isError && (
        <>
          <BranchManager suspended={profile.data.status === "SUSPENDED"} />
          <StaffManager profile={profile.data} />
        </>
      )}
    </>
  );
}
