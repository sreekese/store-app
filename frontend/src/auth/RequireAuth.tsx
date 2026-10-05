import { Link, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { homePaths, loginPaths, type Role } from "./types";
export default function RequireAuth({ role }: { role: Role }) {
  const auth = useAuth(),
    location = useLocation();
  if (auth.loading)
    return (
      <main className="loading" role="status">
        Checking your session…
      </main>
    );
  if (auth.error)
    return (
      <main className="loading">
        <h1>We couldn’t check your session.</h1>
        <p role="alert">Check your connection and try again.</p>
        <button className="button" onClick={auth.retry}>
          Try again
        </button>
      </main>
    );
  if (!auth.user)
    return (
      <Navigate
        replace
        to={
          loginPaths[role] +
          "?returnTo=" +
          encodeURIComponent(location.pathname + location.search)
        }
      />
    );
  if (
    auth.user.role !== role &&
    !(role === "ADMIN" && auth.user.role === "SUPER_ADMIN")
  )
    return (
      <main className="loading">
        <h1>This workspace isn’t available to your account.</h1>
        <Link to={homePaths[auth.user.role]}>Go to my workspace</Link>
      </main>
    );
  return <Outlet />;
}
