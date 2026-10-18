import ThemeSwitch from "../theme/ThemeSwitch";
import { lazy, Suspense } from "react";
import { useAuth } from "../auth/AuthProvider";
import { Link } from "react-router-dom";
import StorefrontPhotos from "../shopper/StorefrontPhotos";
const AdSlot = lazy(() => import("../advertisements/AdSlot"));
const Discover = lazy(() => import("../locations/Discover"));
export default function Home() {
  const auth = useAuth();
  return (
    <>
      <header className="header">
        <Link to="/" className="brand">
          <span>✳</span>nearperk.
        </Link>
        <nav aria-label="Main navigation">
          <a href="#discover">Explore</a>
          <Link to="/app/coupons">My coupons</Link>
          {auth.user?.role === "USER" && (
            <Link to="/app/notifications">Notifications</Link>
          )}
          <ThemeSwitch />
          <Link to={auth.user?.role === "USER" ? "/app" : "/login"}>
            {auth.user?.role === "USER" ? "My account" : "Sign in"}
          </Link>
        </nav>
      </header>
      <main className="container">
        <section className="market-hero" aria-labelledby="market-title">
          <div className="market-hero-copy">
            <p className="market-kicker">
              <span aria-hidden="true">✳</span> BIG FINDS. SMALL DISTANCES.
            </p>
            <h1 id="market-title">Good things are closer.</h1>
            <p className="market-description">
              Your morning coffee. A fresh look. A little retail therapy.
              Discover local stores and offers worth stepping out for.
            </p>
            <div className="market-hero-actions">
              <a className="button" href="#discover">
                Explore nearby stores <span aria-hidden="true">↗</span>
              </a>
              <Link className="market-wallet-link" to="/app/coupons">
                My coupon wallet <span aria-hidden="true">→</span>
              </Link>
            </div>
            <p className="market-hero-note">
              Find a place. Discover an offer. Make it yours.
            </p>
          </div>
          <StorefrontPhotos />
        </section>
        <div
          className="market-intro-strip"
          aria-label="Discover local businesses"
        >
          <p>
            One neighbourhood.
            <br />
            <strong>So much to discover.</strong>
          </p>
          <span>Food &amp; cafés</span>
          <span>Fashion &amp; lifestyle</span>
          <span>Beauty &amp; wellness</span>
          <span>Everyday essentials</span>
        </div>
        <Suspense
          fallback={
            <div className="discovery-loading" role="status">
              Loading nearby discovery…
            </div>
          }
        >
          <AdSlot placement="BELOW_HERO" />
          <Discover />
        </Suspense>
        <section
          className="local-inspiration"
          aria-label="Discover more local offers"
        >
          <img
            src="/images/local-finds.webp"
            alt=""
            width="1536"
            height="1024"
            loading="lazy"
          />
          <div>
            <p className="eyebrow">MAKE A LITTLE ROOM FOR LOCAL</p>
            <h2>
              Everyday finds.
              <br />
              Unexpected favourites.
            </h2>
            <p>
              From your first coffee to your next favourite outfit, explore
              what’s waiting nearby.
            </p>
            <a className="button" href="#discover">
              Discover local offers
            </a>
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
          <a className="button light" href="#discover">
            Find your next local offer
          </a>
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
          <a href="#discover">Explore nearby offers</a>
        </div>
        <div className="footnote">
          Discover local. Support local. Enjoy a little more. · Nearperk
        </div>
      </footer>
    </>
  );
}
