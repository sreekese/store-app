import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { homePaths } from "./types";

// Guests may explore; signed-in management accounts go to their own tools.
export default function ShopperExperience() {
  const auth = useAuth();
  if (auth.loading)
    return (
      <main className="loading" role="status">
        Checking your session…
      </main>
    );
  if (auth.error)
    return (
      <main className="loading">
        <p role="alert">We couldn’t check your session.</p>
        <button onClick={auth.retry}>Try again</button>
      </main>
    );
  if (auth.user && auth.user.role !== "USER")
    return <Navigate replace to={homePaths[auth.user.role]} />;
  return <Outlet />;
}
