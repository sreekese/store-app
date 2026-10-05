import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Field, Feedback, mutate, QueryState } from "../profiles/shared";
import type { Category } from "./types";
function CategoryForm({
  category,
  done,
}: {
  category: Category | null;
  done: (message: string) => void;
}) {
  const [name, setName] = useState(category?.name || ""),
    [description, setDescription] = useState(category?.description || ""),
    [active, setActive] = useState(category?.is_active ?? true),
    client = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      mutate<Category>(
        category ? "/admin/categories/" + category.id : "/admin/categories",
        {
          name,
          description,
          is_active: active,
          ...(category ? { revision: category.revision } : {}),
        },
        category ? "PUT" : "POST",
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["admin-categories"] });
      await client.invalidateQueries({ queryKey: ["offer-categories"] });
      done("Category saved.");
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
      <h3>{category ? "Edit category" : "Add category"}</h3>
      <Field
        label="Category name"
        required
        minLength={2}
        maxLength={100}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <label>
        Category description
        <textarea
          maxLength={500}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      <label className="check-label">
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
        />
        Active category
      </label>
      <small>
        Deactivating a category hides its offers from shoppers. Existing offers
        are preserved.
      </small>
      <Feedback error={save.error} />
      <div className="action-row">
        <button className="button" disabled={save.isPending}>
          Save category
        </button>
        {category && (
          <button
            type="button"
            className="text-button"
            onClick={() => done("")}
          >
            Cancel category edit
          </button>
        )}
      </div>
    </form>
  );
}
export default function Categories() {
  const client = useQueryClient(),
    [editing, setEditing] = useState<Category | null>(null),
    [notice, setNotice] = useState(""),
    [version, setVersion] = useState(0),
    [deleting, setDeleting] = useState<Category | null>(null);
  const query = useQuery({
    queryKey: ["admin-categories"],
    queryFn: () => authorized<Category[]>("/admin/categories"),
    retry: false,
  });
  const remove = useMutation({
    mutationFn: (category: Category) =>
      mutate<void>(
        `/admin/categories/${category.id}?revision=${category.revision}`,
        undefined,
        "DELETE",
      ),
    onSuccess: async () => {
      setDeleting(null);
      setEditing(null);
      setNotice("Category deleted.");
      await client.invalidateQueries({ queryKey: ["admin-categories"] });
      await client.invalidateQueries({ queryKey: ["offer-categories"] });
    },
  });
  return (
    <section className="account-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Organise discovery</p>
          <h2>Offer categories</h2>
        </div>
        <button
          className="text-button"
          onClick={() => {
            setEditing(null);
            setVersion((v) => v + 1);
            void query.refetch();
          }}
        >
          Reload categories
        </button>
      </div>
      <QueryState
        pending={query.isPending}
        error={query.error}
        retry={query.refetch}
      />
      <Feedback success={notice} />
      {query.data?.length === 0 && (
        <p>No categories yet. Add the first category below.</p>
      )}
      <ul className="invitation-list">
        {query.data?.map((category) => (
          <li key={category.id}>
            <div>
              <strong>{category.name}</strong>
              <p>
                {category.is_active ? "Active" : "Inactive"} ·{" "}
                {category.description}
              </p>
            </div>
            <div className="action-row">
              <button
                className="text-button"
                onClick={() => {
                  setEditing(category);
                  setNotice("");
                }}
              >
                Edit category: {category.name}
              </button>
              <button
                className="text-button danger"
                onClick={() => {
                  remove.reset();
                  setDeleting(category);
                }}
              >
                Delete category: {category.name}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {deleting && (
        <div className="notice">
          <p>
            Delete {deleting.name}? Categories used by offers must be
            deactivated instead.
          </p>
          <Feedback error={remove.error} />
          <div className="action-row">
            <button
              className="button secondary"
              disabled={remove.isPending}
              onClick={() => remove.mutate(deleting)}
            >
              Confirm category deletion
            </button>
            <button className="text-button" onClick={() => setDeleting(null)}>
              Keep category
            </button>
          </div>
        </div>
      )}
      <CategoryForm
        key={(editing?.id || "new") + version}
        category={editing}
        done={(message) => {
          setEditing(null);
          setVersion((v) => v + 1);
          setNotice(message);
        }}
      />
    </section>
  );
}
