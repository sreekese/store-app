import ThemeSwitch from "../theme/ThemeSwitch";
import { useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { Link, useLocation } from "react-router-dom";
export default function ShopperHeader() {
  const auth = useAuth();
  const { pathname, search } = useLocation();
  const [accountOpen, setAccountOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [signingOut, setSigningOut] = useState(false);
  return (
    <header className="header">
      <Link to="/" className="brand">
        <span>✳</span>nearperk.
      </Link>
      <nav aria-label="Main navigation">
        <a href={auth.user?.role === "USER" ? "/app#discover" : "/#discover"}>
          Explore
        </a>
        <Link to="/app/coupons">My coupons</Link>
        <ThemeSwitch />
        {auth.user?.role === "USER" ? (
          <div
            className="account-menu"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setAccountOpen(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setAccountOpen(false);
                event.currentTarget
                  .querySelector<HTMLButtonElement>(".account-menu-toggle")
                  ?.focus();
              }
            }}
          >
            <button
              type="button"
              className="account-menu-toggle"
              aria-expanded={accountOpen}
              aria-controls="account-menu-links"
              onClick={() => setAccountOpen(!accountOpen)}
            >
              My account
            </button>
            {accountOpen && (
              <div
                id="account-menu-links"
                className="account-menu-links"
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("a"))
                    setAccountOpen(false);
                }}
              >
                <Link to="/app/profile">My profile</Link>
                <Link to="/app/coupons">Saved coupons and history</Link>
                <Link to="/app/notifications">Notifications</Link>
                <Link to="/app/support">Support</Link>
                <button
                  type="button"
                  disabled={signingOut}
                  onClick={async () => {
                    setSigningOut(true);
                    setLogoutError("");
                    try {
                      await auth.logout();
                    } catch (error) {
                      setLogoutError(
                        error instanceof Error
                          ? error.message
                          : "Unable to sign out. Please try again.",
                      );
                    } finally {
                      setSigningOut(false);
                    }
                  }}
                >
                  {signingOut ? "Signing out…" : "Sign out"}
                </button>
                {logoutError && <p role="alert">{logoutError}</p>}
              </div>
            )}
          </div>
        ) : (
          <Link
            to={
              pathname === "/login" ||
              pathname === "/register" ||
              pathname === "/"
                ? "/login"
                : "/login?returnTo=" + encodeURIComponent(pathname + search)
            }
          >
            Sign in
          </Link>
        )}
      </nav>
    </header>
  );
}
