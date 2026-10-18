export default function StorefrontPhotos() {
  return (
    <div
      className="storefront-photos"
      aria-label="A little inspiration for your next local visit"
    >
      <img
        className="storefront-photo-main"
        src="/images/neighbourhood.webp"
        alt="An inviting café and boutique with plants and a sunny terrace"
        width="1536"
        height="1024"
        fetchPriority="high"
      />
      <div className="photo-caption">
        <span aria-hidden="true">⌖</span> Around the corner. Out of the
        ordinary.
      </div>
      <img
        className="storefront-photo-detail"
        src="/images/local-finds.webp"
        alt="A curated collection of everyday shopping finds"
        width="1536"
        height="1024"
      />
      <span className="photo-stamp" aria-hidden="true">
        Eat. Shop.
        <br />
        Discover.
      </span>
    </div>
  );
}
