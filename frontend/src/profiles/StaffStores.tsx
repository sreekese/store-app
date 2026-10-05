import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Feedback, QueryState, type Store } from "./shared";
export default function StaffStores() {
  const [selected, setSelected] = useState<Store | null>(null);
  const query = useQuery({
    queryKey: ["staff-stores"],
    queryFn: () => authorized<Store[]>("/staff/stores"),
    retry: false,
    refetchInterval: 30000,
  });
  const open = useMutation({
    mutationFn: (id: string) => authorized<Store>("/staff/stores/" + id),
    onSuccess: setSelected,
    onError: () => {
      setSelected(null);
      void query.refetch();
    },
  });
  return (
    <section className="account-panel">
      <p className="eyebrow">Your work locations</p>
      <h2>Assigned stores</h2>
      <p>
        Your store owner manages your access. Select a branch to check your
        current assignment.
      </p>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      {!query.isError && query.data?.length === 0 && (
        <p className="empty-state">
          No active store assignments. Ask your store owner for an invitation or
          access update.
        </p>
      )}
      <div className="branch-grid">
        {!query.isError &&
          query.data?.map((store) => (
            <article className="branch-card" key={store.id}>
              <h3>{store.name}</h3>
              <p>
                {store.address}, {store.city}
              </p>
              <button
                className="text-button"
                disabled={open.isPending}
                onClick={() => open.mutate(store.id)}
              >
                Open store
              </button>
            </article>
          ))}
      </div>
      <Feedback error={open.error} />
      {!query.isError &&
        selected &&
        query.data?.some((store) => store.id === selected.id) && (
          <div className="notice" role="status">
            Access confirmed for {selected.name}. Use the redemption desk to
            validate a shopper’s coupon.
          </div>
        )}
    </section>
  );
}
