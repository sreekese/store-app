export interface Category {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  revision: number;
}
export type Discount =
  "PERCENTAGE" | "FLAT_AMOUNT" | "BOGO" | "FREE_ITEM" | "SPECIAL_PRICE";
export interface OfferFields {
  category_id: string;
  store_id: string | null;
  title: string;
  description: string;
  image_url: string;
  discount_type: Discount;
  discount_value: string;
  minimum_purchase: string;
  maximum_discount: string | null;
  currency: "INR";
  customer_type: "ALL" | "NEW_CUSTOMERS" | "EXISTING_CUSTOMERS";
  terms_conditions: string;
  starts_at: string;
  expires_at: string;
}
export interface Offer extends OfferFields {
  id: string;
  merchant_id: string;
  status: string;
  moderation_note: string;
  approved: boolean;
  admin_hold: boolean;
  revision: number;
  updated_at: string;
}
export interface PublicOffer extends OfferFields {
  id: string;
  business_name: string;
  category_name: string;
  store_name: string;
  matched_store_id: string;
  city: string;
  area: string;
  latitude: number;
  longitude: number;
  distance_meters: number | null;
}
export function discountLabel(offer: OfferFields) {
  switch (offer.discount_type) {
    case "PERCENTAGE":
      return `${Number(offer.discount_value)}% off`;
    case "FLAT_AMOUNT":
      return `₹${Number(offer.discount_value)} off`;
    case "SPECIAL_PRICE":
      return `Special price ₹${Number(offer.discount_value)}`;
    case "BOGO":
      return "Buy one, get one";
    case "FREE_ITEM":
      return "Free item";
  }
}
export function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
