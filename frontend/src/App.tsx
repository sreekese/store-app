import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import ShopperExperience from "./auth/ShopperExperience";
import RequireAuth from "./auth/RequireAuth";
const Reports = lazy(() => import("./analytics/Reports"));
const Billing = lazy(() => import("./billing/Billing"));
const StoreDetail = lazy(() => import("./locations/StoreDetail"));
const AdManager = lazy(() => import("./advertisements/AdManager"));
const Support = lazy(() => import("./trust/Support"));
const Inbox = lazy(() => import("./notifications/Inbox"));
const Wallet = lazy(() => import("./wallet/Wallet"));
const CouponDetail = lazy(() =>
  import("./wallet/Wallet").then((m) => ({ default: m.CouponDetail })),
);
const OfferDetail = lazy(() => import("./offers/OfferDetail"));
const Login = lazy(() => import("./pages/Login"));
const AcceptInvitation = lazy(() => import("./profiles/AcceptInvitation"));
const Workspace = lazy(() => import("./pages/Workspace"));
export default function App() {
  return (
    <Suspense
      fallback={
        <main className="loading" role="status">
          Loading your neighbourhood…
        </main>
      }
    >
      <Routes>
        <Route element={<ShopperExperience />}>
          <Route path="/" element={<Home />} />
          <Route path="/offers/:id" element={<OfferDetail />} />
          <Route path="/stores/:id" element={<StoreDetail />} />
        </Route>
        <Route path="/staff/accept-invitation" element={<AcceptInvitation />} />
        <Route path="/login" element={<Login workspace="USER" />} />
        <Route path="/register" element={<Login workspace="USER" register />} />
        <Route
          path="/merchant/login"
          element={<Login workspace="MERCHANT" />}
        />
        <Route
          path="/merchant/register"
          element={<Login workspace="MERCHANT" register />}
        />
        <Route
          path="/staff/login"
          element={<Login workspace="MERCHANT_STAFF" />}
        />
        <Route path="/admin/login" element={<Login workspace="ADMIN" />} />
        <Route
          path="/superadmin/login"
          element={<Login workspace="SUPER_ADMIN" />}
        />
        <Route element={<RequireAuth role="USER" />}>
          <Route path="/app/support" element={<Support role="USER" />} />
          <Route path="/app/support/:id" element={<Support role="USER" />} />
          <Route path="/app/notifications" element={<Inbox role="USER" />} />
          <Route path="/app" element={<Workspace role="USER" />} />
          <Route path="/app/coupons" element={<Wallet />} />
          <Route path="/app/coupons/:id" element={<CouponDetail />} />
        </Route>
        <Route element={<RequireAuth role="MERCHANT" />}>
          <Route path="/merchant/analytics" element={<Reports />} />
          <Route path="/merchant/billing" element={<Billing />} />
          <Route
            path="/merchant/support"
            element={<Support role="MERCHANT" />}
          />
          <Route
            path="/merchant/support/:id"
            element={<Support role="MERCHANT" />}
          />
          <Route
            path="/merchant/notifications"
            element={<Inbox role="MERCHANT" />}
          />
          <Route
            path="/merchant/dashboard"
            element={<Workspace role="MERCHANT" />}
          />
        </Route>
        <Route element={<RequireAuth role="MERCHANT_STAFF" />}>
          <Route
            path="/staff/support"
            element={<Support role="MERCHANT_STAFF" />}
          />
          <Route
            path="/staff/support/:id"
            element={<Support role="MERCHANT_STAFF" />}
          />
          <Route
            path="/staff/notifications"
            element={<Inbox role="MERCHANT_STAFF" />}
          />
          <Route
            path="/staff/redeem"
            element={<Navigate replace to="/staff/dashboard" />}
          />
          <Route
            path="/staff/dashboard"
            element={<Workspace role="MERCHANT_STAFF" />}
          />
        </Route>
        <Route element={<RequireAuth role="ADMIN" />}>
          <Route path="/admin/analytics" element={<Reports />} />
          <Route path="/admin/support" element={<Support role="ADMIN" />} />
          <Route path="/admin/support/:id" element={<Support role="ADMIN" />} />
          <Route path="/admin/notifications" element={<Inbox role="ADMIN" />} />
          <Route path="/admin/dashboard" element={<Workspace role="ADMIN" />} />
        </Route>
        <Route element={<RequireAuth role="SUPER_ADMIN" />}>
          <Route path="/superadmin/analytics" element={<Reports />} />
          <Route path="/superadmin/billing" element={<Billing superadmin />} />
          <Route path="/superadmin/advertisements" element={<AdManager />} />
          <Route
            path="/superadmin/support"
            element={<Support role="SUPER_ADMIN" />}
          />
          <Route
            path="/superadmin/support/:id"
            element={<Support role="SUPER_ADMIN" />}
          />
          <Route
            path="/superadmin/notifications"
            element={<Inbox role="SUPER_ADMIN" />}
          />
          <Route
            path="/superadmin/dashboard"
            element={<Workspace role="SUPER_ADMIN" />}
          />
        </Route>
        <Route
          path="*"
          element={
            <main className="loading">
              <h1>That page isn't here yet.</h1>
              <Link to="/">Back to Nearperk</Link>
            </main>
          }
        />
      </Routes>
    </Suspense>
  );
}
