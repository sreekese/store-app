import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { authorized } from "../auth/client";
import {
  labels,
  loginPaths,
  homePaths,
  type Role,
  type User,
} from "../auth/types";
const DailyPicks = lazy(() => import("../daily/DailyPicks"));
const PolicyEditor = lazy(() => import("../daily/PolicyEditor"));
const Dashboard = lazy(() => import("../dashboards/Dashboard"));
const RedemptionDesk = lazy(() => import("../redemptions/RedemptionDesk"));
const Campaigns = lazy(() => import("../offers/Campaigns"));
const ClaimReceipts = lazy(() =>
  import("../offers/ClaimCoupons").then((m) => ({ default: m.ClaimReceipts })),
);
const MerchantOffers = lazy(() => import("../offers/MerchantOffers"));
const Categories = lazy(() => import("../offers/Categories"));
const OfferModeration = lazy(() => import("../offers/OfferModeration"));
const Discover = lazy(() => import("../locations/Discover"));
const ShopperProfile = lazy(() => import("../profiles/ShopperProfile"));
const MerchantWorkspace = lazy(() => import("../profiles/MerchantWorkspace"));
const AdminReviews = lazy(() => import("../profiles/AdminReviews"));
const StaffStores = lazy(() => import("../profiles/StaffStores"));
const endpoints: Record<Role, string> = {
  USER: "shopper",
  MERCHANT: "merchant",
  MERCHANT_STAFF: "staff",
  ADMIN: "admin",
  SUPER_ADMIN: "superadmin",
};
export default function Workspace({ role }: { role: Role }) {
  const auth = useAuth(),
    navigate = useNavigate(),
    [logoutError, setLogoutError] = useState(""),
    [busy, setBusy] = useState(false);
  const query = useQuery({
    queryKey: ["workspace", role, auth.user?.id],
    queryFn: () => authorized<User>("/workspaces/" + endpoints[role]),
    retry: false,
  });
  async function logout() {
    setBusy(true);
    setLogoutError("");
    try {
      await auth.logout();
      navigate(loginPaths[role], { replace: true });
    } catch (error) {
      setLogoutError(
        error instanceof Error ? error.message : "Sign out failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="header">
        <Link to={homePaths[role]} className="brand">
          ✳ nearperk.
        </Link>
        <nav aria-label="Account navigation">
          <Link
            to={homePaths[role].replace(/\/dashboard$/, "") + "/notifications"}
          >
            Notifications
          </Link>
          <Link to={homePaths[role].replace(/\/dashboard$/, "") + "/support"}>
            Support
          </Link>
          {(role === "MERCHANT" || role === "SUPER_ADMIN") && (
            <Link
              to={
                role === "MERCHANT"
                  ? "/merchant/billing"
                  : "/superadmin/billing"
              }
            >
              Billing
            </Link>
          )}
          {role === "SUPER_ADMIN" && (
            <Link to="/superadmin/advertisements">Advertisements</Link>
          )}
          {["MERCHANT", "ADMIN", "SUPER_ADMIN"].includes(role) && (
            <Link to={homePaths[role].replace("/dashboard", "/analytics")}>
              Analytics
            </Link>
          )}
          <span>{auth.user?.display_name}</span>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => void logout()}
          >
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </nav>
      </header>
      <main className="container workspace-shell">
        <p className="eyebrow">{labels[role]} workspace</p>
        <h1>Welcome, {auth.user?.display_name}.</h1>
        {logoutError && (
          <p role="alert" className="form-error">
            {logoutError}
          </p>
        )}
        {query.isPending ? (
          <p role="status">Checking workspace access…</p>
        ) : query.isError ? (
          <div className="notice">
            <p role="alert">{query.error.message}</p>
            <button
              className="text-button"
              onClick={() => void query.refetch()}
            >
              Try again
            </button>
          </div>
        ) : (
          <>
            <span className="badge">
              ✓ Account access verified by the server
            </span>
            <section className="account-panel">
              <h2>Your account is ready.</h2>
              <p>Signed in as {query.data.email}.</p>
              <p>
                {role === "USER"
                  ? "Explore nearby stores and offers. Claim available coupons and manage your private coupon wallet."
                  : role === "MERCHANT"
                    ? "Manage your business profile, verification, branches, and staff."
                    : role === "MERCHANT_STAFF"
                      ? "Validate and redeem coupons at your assigned branches."
                      : "Monitor platform activity and manage business verification, offers, categories, and campaigns."}
              </p>
            </section>
            <div className="workspace-tools">
              <Suspense fallback={<p role="status">Loading your tools…</p>}>
                {role !== "USER" && <Dashboard role={role} />}
                {role === "MERCHANT" && <DailyPicks />}
                {role === "SUPER_ADMIN" && (
                  <>
                    <PolicyEditor />
                    <DailyPicks superadmin />
                  </>
                )}
                {role === "USER" ? (
                  <>
                    <Discover />
                    <ClaimReceipts />
                    <ShopperProfile />
                  </>
                ) : role === "MERCHANT" ? (
                  <>
                    <RedemptionDesk />
                    <MerchantWorkspace />
                    <MerchantOffers />
                    <Campaigns />
                  </>
                ) : role === "MERCHANT_STAFF" ? (
                  <>
                    <RedemptionDesk staff />
                    <StaffStores />
                  </>
                ) : (
                  <>
                    <AdminReviews />
                    <OfferModeration />
                    <Categories />
                    <Campaigns admin />
                  </>
                )}
              </Suspense>
            </div>
            <div className="notice">
              Your session is protected. Signing out revokes this session,
              including its existing access token.
            </div>
          </>
        )}
      </main>
    </>
  );
}
