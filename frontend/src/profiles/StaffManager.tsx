import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import {
  Field,
  Feedback,
  mutate,
  QueryState,
  StoreChoices,
  type Merchant,
  type Store,
  type StaffMember,
  type Invitation,
} from "./shared";
function Pages({
  name,
  offset,
  count,
  change,
}: {
  name: string;
  offset: number;
  count: number;
  change: (n: number) => void;
}) {
  return (
    <div className="action-row">
      <button
        disabled={!offset}
        onClick={() => change(Math.max(0, offset - 25))}
      >
        Previous {name}
      </button>
      <button
        disabled={count < 25 || offset + 25 > 10000}
        onClick={() => change(offset + 25)}
      >
        More {name}
      </button>
    </div>
  );
}
function StaffEditor({
  person,
  stores,
  verified,
  refresh,
}: {
  person: StaffMember;
  stores: Store[];
  verified: boolean;
  refresh: () => void;
}) {
  const [selected, setSelected] = useState(person.store_ids);
  const save = useMutation({
    mutationFn: (ids: string[]) =>
      mutate<void>(`/merchant/staff/${person.id}/assignments`, {
        revision: person.revision,
        store_ids: ids,
      }),
    onSuccess: refresh,
  });
  return (
    <article className="staff-card">
      <h3>{person.display_name}</h3>
      <p>{person.email}</p>
      <p>
        {!person.account_active
          ? "Account unavailable"
          : person.store_ids.length
            ? "Assigned to this business"
            : "Access revoked for this business"}
      </p>
      <StoreChoices
        stores={stores}
        selected={selected}
        onChange={setSelected}
        disabled={!verified || !person.account_active || save.isPending}
      />
      <Feedback
        error={save.error}
        success={save.isSuccess ? "Store access updated." : undefined}
      />
      <div className="action-row">
        <button
          className="button small"
          disabled={
            !verified ||
            !person.account_active ||
            save.isPending ||
            !selected.length
          }
          onClick={() => save.mutate(selected)}
        >
          {person.store_ids.length
            ? "Save assignments"
            : "Restore selected access"}
        </button>
        <button
          className="text-button danger"
          disabled={save.isPending || !person.store_ids.length}
          onClick={() => save.mutate([])}
        >
          Revoke all access
        </button>
      </div>
    </article>
  );
}
interface Audit {
  id: string;
  created_at: string;
  action: string;
  actor: string;
  subject: string;
  before_stores: string[];
  stores: string[];
}
function StaffAudit({ merchantId }: { merchantId: string }) {
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["staff-audit", merchantId, offset],
    queryFn: () =>
      authorized<Audit[]>(`/merchant/staff-audit?offset=${offset}`),
    retry: false,
    gcTime: 0,
  });
  return (
    <section>
      <h3>Staff access history</h3>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {query.data && !query.isError && (
        <>
          {!query.data.length && <p>No staff access changes recorded.</p>}
          {query.data.map((a) => (
            <article className="notification-item" key={a.id}>
              <strong>{a.action.replaceAll("_", " ")}</strong>
              <p>
                {a.subject} · by {a.actor}
              </p>
              {a.action === "STAFF_ASSIGNMENTS_CHANGED" ? (
                <p>
                  {a.before_stores.join(", ") || "No branches"} →{" "}
                  {a.stores.join(", ") || "No branches"}
                </p>
              ) : (
                !!a.stores.length && <p>{a.stores.join(", ")}</p>
              )}
              <small>{new Date(a.created_at).toLocaleString()}</small>
            </article>
          ))}
          <Pages
            name="history entries"
            offset={offset}
            count={query.data.length}
            change={setOffset}
          />
        </>
      )}
    </section>
  );
}
export default function StaffManager({ profile }: { profile: Merchant }) {
  const client = useQueryClient(),
    verified = profile.status === "VERIFIED";
  const [staffOffset, setStaffOffset] = useState(0),
    [inviteOffset, setInviteOffset] = useState(0),
    [status, setStatus] = useState(""),
    [history, setHistory] = useState(false);
  const stores = useQuery({
    queryKey: ["merchant-stores"],
    queryFn: () => authorized<Store[]>("/merchant/stores"),
    retry: false,
  });
  const staff = useQuery({
    queryKey: ["merchant-staff", profile.id, staffOffset],
    queryFn: () =>
      authorized<StaffMember[]>(
        "/merchant/staff" + (staffOffset ? `?offset=${staffOffset}` : ""),
      ),
    retry: false,
    gcTime: 0,
  });
  const params = new URLSearchParams();
  if (inviteOffset) params.set("offset", String(inviteOffset));
  if (status) params.set("status", status);
  const invitations = useQuery({
    queryKey: ["merchant-invitations", profile.id, inviteOffset, status],
    queryFn: () =>
      authorized<Invitation[]>(
        "/merchant/invitations" + (params.size ? `?${params}` : ""),
      ),
    retry: false,
    gcTime: 0,
  });
  const [email, setEmail] = useState(""),
    [selected, setSelected] = useState<string[]>([]),
    [link, setLink] = useState(""),
    [copied, setCopied] = useState("");
  function refresh() {
    setLink("");
    setCopied("");
    void client.invalidateQueries({ queryKey: ["merchant-staff"] });
    void client.invalidateQueries({ queryKey: ["merchant-invitations"] });
    void client.invalidateQueries({ queryKey: ["staff-audit"] });
  }
  const invite = useMutation({
    mutationFn: (id?: string) =>
      id
        ? mutate<{ token: string }>(
            `/merchant/invitations/${id}/reissue`,
            undefined,
            "POST",
          )
        : mutate<{ token: string }>(
            "/merchant/invitations",
            { email, store_ids: selected },
            "POST",
          ),
    onSuccess: (data) => {
      refresh();
      setLink(
        `${window.location.origin}/staff/accept-invitation#token=${data.token}`,
      );
      setEmail("");
    },
  });
  const cancel = useMutation({
    mutationFn: (id: string) =>
      mutate<void>(`/merchant/invitations/${id}`, undefined, "DELETE"),
    onSuccess: refresh,
  });
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied("Invitation link copied.");
    } catch {
      setCopied("Select and copy the link below.");
    }
  }
  const busy = invite.isPending || cancel.isPending || invitations.isFetching;
  return (
    <section className="account-panel">
      <p className="eyebrow">Your people</p>
      <h2>Staff access</h2>
      <p>
        Changes apply only to this business. Revoking access preserves the
        account, previous redemptions, and assignments at other businesses.
      </p>
      {!verified && (
        <p className="notice">
          Staff invitations and assignments become available after verification.
          You can still revoke existing access.
        </p>
      )}
      <button
        disabled={staff.isFetching || invitations.isFetching}
        onClick={refresh}
      >
        Refresh staff access
      </button>
      <QueryState
        pending={staff.isPending}
        error={staff.error}
        retry={staff.refetch}
      />
      <QueryState
        pending={stores.isPending}
        error={stores.error}
        retry={stores.refetch}
      />
      {staff.data && !staff.isError && (
        <>
          {!staff.data.length && (
            <p className="empty-state">No staff assigned yet.</p>
          )}
          {!stores.isError &&
            staff.data.map((person) => (
              <StaffEditor
                key={`${person.id}-${person.revision}`}
                person={person}
                stores={stores.data || []}
                verified={verified}
                refresh={refresh}
              />
            ))}
          <Pages
            name="staff"
            offset={staffOffset}
            count={staff.data.length}
            change={setStaffOffset}
          />
        </>
      )}
      <h3>Invite a team member</h3>
      <p>
        Each person uses their own staff account. Links expire after seven days.
        Reissuing a link invalidates older invitations for the same email in
        this business.
      </p>
      <form
        className="auth-form profile-form"
        onSubmit={(e) => {
          e.preventDefault();
          setLink("");
          invite.mutate(undefined);
        }}
      >
        <Field
          label="Staff email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={!verified || busy}
        />
        <StoreChoices
          stores={stores.isError ? [] : stores.data || []}
          selected={selected}
          onChange={setSelected}
          disabled={!verified || busy || stores.isError}
        />
        <Feedback error={invite.error} />
        <button
          className="button"
          disabled={
            !verified ||
            busy ||
            !selected.length ||
            stores.isError ||
            stores.isPending
          }
        >
          Create invitation link
        </button>
      </form>
      {link && (
        <div className="invitation-result">
          <label>
            Share this invitation link
            <input readOnly value={link} onFocus={(e) => e.target.select()} />
          </label>
          <button className="text-button" onClick={() => void copy()}>
            Copy link
          </button>
          <button className="text-button" onClick={() => setLink("")}>
            Hide invitation link
          </button>
          <p role="status">
            {copied ||
              "Share this link privately with the invited staff member. It is shown only here and is not emailed automatically."}
          </p>
        </div>
      )}
      <h3>Recent invitations</h3>
      <label>
        Invitation status
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setInviteOffset(0);
          }}
        >
          <option value="">All invitations</option>
          {["PENDING", "ACCEPTED", "CANCELLED", "EXPIRED"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <QueryState
        pending={invitations.isPending}
        error={invitations.error}
        retry={invitations.refetch}
      />
      <Feedback error={cancel.error} />
      {invitations.data && !invitations.isError && (
        <>
          {!invitations.data.length && <p>No invitations yet.</p>}
          <ul className="invitation-list">
            {invitations.data.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.email}</strong>
                  <p>
                    {item.status} · Expires{" "}
                    {new Date(item.expires_at).toLocaleString()}
                  </p>
                  <p>
                    {item.store_ids
                      .map(
                        (id) =>
                          stores.data?.find((s) => s.id === id)?.name ||
                          "Assigned branch",
                      )
                      .join(", ")}
                  </p>
                </div>
                <div className="action-row">
                  {item.status === "PENDING" && (
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() => cancel.mutate(item.id)}
                    >
                      Cancel invitation
                    </button>
                  )}
                  {item.status !== "ACCEPTED" && (
                    <button
                      className="text-button"
                      disabled={busy || !verified}
                      onClick={() => {
                        setLink("");
                        invite.mutate(item.id);
                      }}
                    >
                      Reissue invitation
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <Pages
            name="invitations"
            offset={inviteOffset}
            count={invitations.data.length}
            change={setInviteOffset}
          />
        </>
      )}
      <details onToggle={(e) => setHistory(e.currentTarget.open)}>
        <summary>View staff access history</summary>
        {history && <StaffAudit merchantId={profile.id} />}
      </details>
    </section>
  );
}
