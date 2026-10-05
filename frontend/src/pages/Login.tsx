import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { registerAccount } from "../auth/client";
import {
  homePaths,
  labels,
  loginPaths,
  safeReturnTo,
  type Role,
} from "../auth/types";
export default function Login({
  workspace,
  register = false,
}: {
  workspace: Role;
  register?: boolean;
}) {
  const auth = useAuth(),
    navigate = useNavigate(),
    [params] = useSearchParams();
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [show, setShow] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (register) {
        if (workspace !== "USER" && workspace !== "MERCHANT") return;
        await registerAccount({
          email,
          password,
          display_name: name,
          role: workspace,
        });
      }
      const user = await auth.login(email, password, workspace);
      setPassword("");
      navigate(safeReturnTo(user.role, params.get("returnTo")), {
        replace: true,
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  const registerPath =
    workspace === "USER" ? "/register" : "/merchant/register";
  return (
    <main className="login">
      <section>
        <Link to="/" className="brand">
          ✳ nearperk.
        </Link>
        <p className="eyebrow">LOCAL FEELS REWARDING</p>
        <h1>
          Good things
          <br />
          start here.
        </h1>
        <p>Your neighbourhood, a little more rewarding.</p>
      </section>
      <section>
        <Link to="/">← Back to offers</Link>
        <div>
          <p className="eyebrow">{labels[workspace]}</p>
          <h2>
            {register ? "Create your account" : labels[workspace] + " sign in"}
          </h2>
        </div>
        <p>
          {register
            ? "A little saving. A little love for local."
            : "Welcome back. Your neighbourhood is waiting."}
        </p>
        {auth.user ? (
          <div className="notice">
            You’re signed in as {auth.user.display_name}.{" "}
            <Link to={homePaths[auth.user.role]}>Open your workspace →</Link>
            <button
              className="text-button"
              onClick={() =>
                void auth.logout().catch((e) => setError(e.message))
              }
            >
              Sign out to switch accounts
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="auth-form">
            {register && (
              <label>
                Full name
                <input
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={100}
                />
              </label>
            )}
            <label>
              Email address
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={320}
              />
            </label>
            <label>
              Password
              <div className="password-field">
                <input
                  type={show ? "text" : "password"}
                  aria-label="Password"
                  autoComplete={register ? "new-password" : "current-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={register ? 12 : 1}
                  maxLength={128}
                />
                <button
                  type="button"
                  aria-label={show ? "Hide password" : "Show password"}
                  onClick={() => setShow(!show)}
                >
                  {show ? "Hide" : "Show"}
                </button>
              </div>
              {register && <small>Use 12–128 characters.</small>}
            </label>
            <button
              className="button"
              disabled={busy || auth.loading}
              type="submit"
            >
              {busy
                ? "Please wait…"
                : register
                  ? "Create account →"
                  : "Sign in →"}
            </button>
          </form>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {!auth.user && (workspace === "USER" || workspace === "MERCHANT") && (
          <p>
            {register ? "Already have an account?" : "New to Nearperk?"}{" "}
            <Link
              className="inline-link"
              to={register ? loginPaths[workspace] : registerPath}
            >
              {register ? "Sign in" : "Create an account"}
            </Link>
          </p>
        )}
        {(workspace === "MERCHANT_STAFF" ||
          workspace === "ADMIN" ||
          workspace === "SUPER_ADMIN") && (
          <p className="auth-help">
            Use the account provided by your store owner or platform
            administrator.
          </p>
        )}
        {register && workspace === "MERCHANT" && (
          <div className="notice">
            Creating an account does not verify your business. Store setup and
            verification are available after registration.
          </div>
        )}
      </section>
    </main>
  );
}
