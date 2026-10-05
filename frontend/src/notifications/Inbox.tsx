import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { useAuth } from "../auth/AuthProvider";
import { homePaths, type Role } from "../auth/types";
import { Feedback, QueryState } from "../profiles/shared";
interface Note {
  id: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
  stale: boolean;
}
interface Page {
  items: Note[];
  unread_count: number;
  next_offset: number | null;
}
interface Preferences {
  email_enabled: boolean;
  daily_enabled: boolean;
  email_mode: string;
}
function DeliveryFailures() {
  const [offset, setOffset] = useState(0),
    client = useQueryClient();
  const query = useQuery({
    queryKey: ["notification-failures", offset],
    queryFn: () =>
      authorized<
        { id: string; kind: string; attempts: number; last_error: string }[]
      >(`/notifications/operations/failed?offset=${offset}`),
    retry: false,
  });
  const retry = useMutation({
    mutationFn: (id: string) =>
      authorized(`/notifications/operations/${id}/retry`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["notification-failures"] });
    },
  });
  return (
    <section className="account-panel">
      <h2>Failed notification jobs</h2>
      <p>
        Retry preserves the original delivery identity. Expired or ineligible
        reminders are skipped.
      </p>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      <Feedback
        error={retry.error}
        success={retry.isSuccess ? "Retry queued." : undefined}
      />
      {!query.isError &&
        query.data?.map((j) => (
          <article key={j.id}>
            <p>
              {j.kind} · {j.attempts} attempts · {j.last_error}
            </p>
            <button
              disabled={retry.isPending}
              onClick={() => retry.mutate(j.id)}
            >
              Retry job
            </button>
          </article>
        ))}
      {query.data?.length === 0 && !query.isError && (
        <p>No failed notification jobs.</p>
      )}
      <button
        disabled={!offset}
        onClick={() => setOffset(Math.max(0, offset - 25))}
      >
        Previous jobs
      </button>
      <button
        disabled={!query.data || query.data.length < 25}
        onClick={() => setOffset(offset + 25)}
      >
        More jobs
      </button>
    </section>
  );
}
export default function Inbox({ role }: { role: Role }) {
  const auth = useAuth(),
    client = useQueryClient(),
    [offset, setOffset] = useState(0),
    [unread, setUnread] = useState(false);
  const query = useQuery({
    queryKey: ["notifications", auth.user?.id, unread, offset],
    queryFn: () =>
      authorized<Page>(`/notifications?unread=${unread}&offset=${offset}`),
    retry: false,
    refetchInterval: 30000,
    gcTime: 0,
  });
  const prefs = useQuery({
    queryKey: ["notification-preferences", auth.user?.id],
    queryFn: () => authorized<Preferences>("/notifications/preferences"),
    retry: false,
    gcTime: 0,
  });
  const read = useMutation({
    mutationFn: (id: string) =>
      authorized(
        id === "all" ? "/notifications/read-all" : `/notifications/${id}/read`,
        { method: "POST" },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  const preferences = useMutation({
    mutationFn: (data: Preferences) =>
      authorized<Preferences>("/notifications/preferences", {
        method: "PUT",
        body: JSON.stringify({
          email_enabled: data.email_enabled,
          daily_enabled: data.daily_enabled,
        }),
      }),
    onSuccess: () => {
      void prefs.refetch();
    },
  });
  return (
    <>
      <header className="header">
        <Link className="brand" to={homePaths[role]}>
          ✳ nearperk.
        </Link>
        <Link to={homePaths[role]}>Back to dashboard</Link>
      </header>
      <main className="container workspace-shell">
        <h1>Notifications</h1>
        <section className="account-panel notification-inbox">
          <p>
            Updates are delivered in the background. Open a coupon to check its
            current status.
          </p>
          <label>
            <input
              type="checkbox"
              checked={unread}
              onChange={(e) => {
                setUnread(e.target.checked);
                setOffset(0);
              }}
            />{" "}
            Unread only
          </label>
          <button
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            Refresh notifications
          </button>
          <QueryState
            pending={query.isPending}
            error={query.error}
            retry={query.refetch}
          />
          <Feedback error={read.error} />
          {query.data && !query.isError && (
            <>
              <p>{query.data.unread_count} unread</p>
              <button
                disabled={!query.data.unread_count || read.isPending}
                onClick={() => read.mutate("all")}
              >
                Mark all as read
              </button>
              {query.data.items.length === 0 && (
                <p>No notifications here yet.</p>
              )}
              {query.data.items.map((n) => (
                <article className="notification-item" key={n.id}>
                  <h2>{n.title}</h2>
                  <p>{n.body}</p>
                  <p>
                    <time dateTime={n.created_at}>
                      {new Date(n.created_at).toLocaleString()}
                    </time>{" "}
                    · {n.read_at ? "Read" : "Unread"}
                  </p>
                  {n.stale && (
                    <p>
                      This update is no longer current. Check the latest coupon
                      status.
                    </p>
                  )}
                  {n.link.startsWith("/") &&
                    !n.link.startsWith("//") &&
                    !n.link.includes("\\") && (
                      <Link to={n.link}>Open details</Link>
                    )}
                  {!n.read_at && (
                    <button
                      disabled={read.isPending}
                      onClick={() => read.mutate(n.id)}
                    >
                      Mark as read
                    </button>
                  )}
                </article>
              ))}
              <button
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                Previous notifications
              </button>
              <button
                disabled={query.data.next_offset === null}
                onClick={() => setOffset(query.data!.next_offset!)}
              >
                More notifications
              </button>
            </>
          )}
        </section>
        <section className="account-panel">
          <h2>Notification preferences</h2>
          <QueryState
            pending={prefs.isPending}
            error={prefs.error}
            retry={prefs.refetch}
          />
          <Feedback
            error={preferences.error}
            success={preferences.isSuccess ? "Preferences saved." : undefined}
          />
          {prefs.data && !prefs.isError && (
            <>
              <p>
                Email is currently in preview mode: messages are stored locally
                and are not sent.
              </p>
              <label>
                <input
                  type="checkbox"
                  disabled={preferences.isPending}
                  checked={prefs.data.email_enabled}
                  onChange={(e) =>
                    preferences.mutate({
                      ...prefs.data!,
                      email_enabled: e.target.checked,
                    })
                  }
                />{" "}
                Email notifications
              </label>
              {role === "USER" && (
                <>
                  <label>
                    <input
                      type="checkbox"
                      disabled={preferences.isPending}
                      checked={prefs.data.daily_enabled}
                      onChange={(e) =>
                        preferences.mutate({
                          ...prefs.data!,
                          daily_enabled: e.target.checked,
                        })
                      }
                    />{" "}
                    Daily coupon suggestions
                  </label>
                  <p>
                    Daily suggestions use your most recent saved search area
                    from the last 30 days. They never claim a coupon for you.
                  </p>
                </>
              )}
            </>
          )}
        </section>
        {role === "SUPER_ADMIN" && <DeliveryFailures />}
      </main>
    </>
  );
}
