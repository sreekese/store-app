import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { raw } from "../auth/client";
import { Field, Feedback, QueryState } from "./shared";
interface Preview {
  email: string;
  business_name: string;
  stores: string[];
  expires_at: string;
}
export default function AcceptInvitation() {
  const location = useLocation();
  return <InvitationForm key={location.hash} />;
}
function InvitationForm() {
  const [token] = useState(
    () => new URLSearchParams(window.location.hash.slice(1)).get("token") || "",
  );
  const [name, setName] = useState(""),
    [password, setPassword] = useState("");
  // Fragment tokens are never sent in request URLs, server logs, or referrer headers.
  const preview = useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: () =>
      raw<Preview>("/staff/invitations/preview", {
        method: "POST",
        body: JSON.stringify({ token }),
      }),
    enabled: !!token,
    retry: false,
    gcTime: 0,
  });
  const accept = useMutation({
    mutationFn: () =>
      raw("/staff/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ token, display_name: name, password }),
      }),
    onSuccess: () => {
      setPassword("");
      window.history.replaceState(null, "", window.location.pathname);
    },
  });
  return (
    <>
      <header className="header">
        <Link className="brand" to="/">
          ✳ nearperk.
        </Link>
        <Link className="text-button" to="/staff/login">
          Staff sign in
        </Link>
      </header>
      <main className="container invitation-page">
        <p className="eyebrow">Good teams start here</p>
        <h1>You’re invited.</h1>
        <section className="account-panel">
          {!token ? (
            <p role="alert">
              This link is missing its invitation token. Ask your store owner
              for a new link.
            </p>
          ) : accept.isSuccess ? (
            <>
              <h2>You’re on the team.</h2>
              <p>
                Your store access is ready. Sign in using {preview.data?.email}{" "}
                and your password.
              </p>
              <Link className="button" to="/staff/login">
                Continue to staff sign in
              </Link>
            </>
          ) : (
            <>
              <QueryState
                pending={preview.isPending}
                error={preview.error}
                retry={preview.refetch}
              />
              {preview.data && !preview.isError && (
                <>
                  <h2>Join {preview.data.business_name}</h2>
                  <p>
                    Invited email: <strong>{preview.data.email}</strong>
                  </p>
                  <p>Assigned to {preview.data.stores.join(", ")}</p>
                  <p>
                    This invitation expires{" "}
                    {new Date(preview.data.expires_at).toLocaleDateString()}.
                  </p>
                  <form
                    className="auth-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      accept.mutate();
                    }}
                  >
                    <Field
                      label="Your name"
                      required
                      maxLength={100}
                      autoComplete="name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                    <Field
                      label="Staff password"
                      type="password"
                      required
                      minLength={12}
                      maxLength={128}
                      autoComplete="off"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                    <small>
                      Already have a staff account? Enter its current password.
                      Otherwise choose a new password of at least 12 characters.
                    </small>
                    <Feedback error={accept.error} />
                    <button className="button" disabled={accept.isPending}>
                      {accept.isPending ? "Joining…" : "Accept invitation"}
                    </button>
                  </form>
                </>
              )}
            </>
          )}
        </section>
      </main>
    </>
  );
}
