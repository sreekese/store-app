import { lazy, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthProvider";
import { homePaths } from "../auth/types";
import { Link } from "react-router-dom";
import { getPlatformStatus } from "../api/client";
const Discover = lazy(() => import("../locations/Discover"));
export default function Home() {
  const auth = useAuth();
  const status = useQuery({
    queryKey: ["platform-status"],
    queryFn: getPlatformStatus,
  });
  return (
    <>
      <header className="header">
        <Link to="/" className="brand">
          <span>✳</span>nearperk.
        </Link>
        <nav aria-label="Main navigation">
          <a href="#discover">Discover</a>
          {auth.user?.role === "USER" && (
            <Link to="/app/notifications">Notifications</Link>
          )}
          <Link to={auth.user ? homePaths[auth.user.role] : "/login"}>
            {auth.user ? "My account" : "Sign in"}
          </Link>
        </nav>
      </header>
      <main className="container">
        <div className="intro">
          <p className="eyebrow">
            YOUR NEIGHBOURHOOD. A LITTLE MORE REWARDING.
          </p>
          <h1>Good things are closer.</h1>
          <p>Little perks from the places around you.</p>
        </div>
        <section className="hero">
          <div>
            <p className="eyebrow">LOCAL FEELS REWARDING</p>
            <h2>
              A familiar street.
              <br />A new favourite.
            </h2>
            <p>
              We're getting your neighbourhood ready for nearby offers,
              <br className="desktop" /> daily coupons, and a little more love
              for local.
            </p>
            <a className="button" href="#discover">
              Explore nearby stores ↗
            </a>
          </div>
          <div className="ticket" aria-hidden="true">
            <span className="eyebrow">A LITTLE LOVE FOR LOCAL</span>
            <strong>
              hello,
              <br />
              neighbour.
            </strong>
            <div>Good things, just around the corner. ✳</div>
          </div>
        </section>
        <Suspense
          fallback={
            <div className="discovery-loading" role="status">
              Loading nearby discovery…
            </div>
          }
        >
          <Discover />
        </Suspense>
        <section className="readiness">
          <div>
            <p className="eyebrow">YOUR LOCAL ACCOUNT</p>
            <h2>Your neighbourhood account starts here.</h2>
            <p>
              Create an account or sign in to discover offers from local
              businesses.
            </p>
          </div>
          <div className="status-card" aria-live="polite">
            {status.isPending ? (
              <p role="status">Connecting to the platform…</p>
            ) : status.isError ? (
              <>
                <p role="alert">The platform is temporarily unavailable.</p>
                <button onClick={() => void status.refetch()}>Try again</button>
              </>
            ) : (
              <>
                <span className="badge">● API connected</span>
                <h3>{status.data.name}</h3>
                <p>Platform v{status.data.version}</p>
              </>
            )}
          </div>
        </section>
        <section className="steps">
          <article>
            <span>01</span>
            <h3>Find your neighbourhood</h3>
            <p>Discover nearby stores with GPS or choose a place yourself.</p>
          </article>
          <article>
            <span>02</span>
            <h3>Claim a little perk</h3>
            <p>Clear terms, daily allowances, and your own coupon wallet.</p>
          </article>
          <article>
            <span>03</span>
            <h3>Make someone's day</h3>
            <p>
              Visit a local store and let staff securely redeem your coupon.
            </p>
          </article>
        </section>
        <section className="cta">
          <p className="eyebrow">SMALL SHOPS. BIG NEIGHBOURHOOD ENERGY.</p>
          <h2>
            Your next favourite place
            <br />
            might be around the corner.
          </h2>
          <p>We're building a better way to discover local.</p>
          <Link className="button light" to="/merchant/login">
            For local businesses ↗
          </Link>
        </section>
      </main>
      <footer>
        <div className="footer-grid">
          <div className="brand">✳ nearperk.</div>
          <p>
            Little perks. Familiar streets.
            <br />
            Good things, closer to home.
          </p>
          <Link to="/app/coupons">My coupon wallet</Link>
          <Link to="/app/support">Support</Link>
          <Link to="/merchant/login">Store owner sign in ↗</Link>
        </div>
        <div className="footnote">
          Nearperk · Development build · Offer discovery available · Coupon
          claiming available
        </div>
      </footer>
    </>
  );
}
