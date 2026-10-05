export type Placement = "BELOW_DAILY" | "BELOW_OFFERS";
export interface AdFields {
  sponsor: string;
  headline: string;
  body: string;
  image_url: string;
  image_alt: string;
  cta: string;
  placement: Placement;
  destination_type: "DISCOVER" | "STORE" | "OFFER";
  store_id: string | null;
  offer_id: string | null;
  starts_at: string;
  expires_at: string;
}
export interface Ad extends AdFields {
  id: string;
  revision: number;
  status: string;
  updated_at: string;
}
export interface Card {
  id: string;
  sponsor: string;
  headline: string;
  body: string;
  image_url: string;
  image_alt: string;
  cta: string;
  placement: Placement;
  href: string;
  valid_until: string;
}
export interface Page<T> {
  items: T[];
  next_offset: number | null;
}
export const placements: Record<Placement, string> = {
  BELOW_DAILY: "Below daily coupons",
  BELOW_OFFERS: "Below nearby offers",
};
