export type Role =
  "USER" | "MERCHANT" | "MERCHANT_STAFF" | "ADMIN" | "SUPER_ADMIN";
export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
}
export interface AuthResult {
  access_token: string;
  expires_in: number;
  token_type: string;
  user: User;
}
export const labels: Record<Role, string> = {
  USER: "Shopper",
  MERCHANT: "Store admin",
  MERCHANT_STAFF: "Staff",
  ADMIN: "Admin",
  SUPER_ADMIN: "Superadmin",
};
export const loginPaths: Record<Role, string> = {
  USER: "/login",
  MERCHANT: "/merchant/login",
  MERCHANT_STAFF: "/staff/login",
  ADMIN: "/admin/login",
  SUPER_ADMIN: "/superadmin/login",
};
export const homePaths: Record<Role, string> = {
  USER: "/app",
  MERCHANT: "/merchant/dashboard",
  MERCHANT_STAFF: "/staff/dashboard",
  ADMIN: "/admin/dashboard",
  SUPER_ADMIN: "/superadmin/dashboard",
};
export function safeReturnTo(role: Role, value: string | null): string {
  if (
    role !== "USER" ||
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\")
  )
    return homePaths[role];
  const parsed = new URL(value, "https://nearperk.invalid");
  if (parsed.origin !== "https://nearperk.invalid") return homePaths[role];
  if (
    parsed.pathname === "/app" ||
    parsed.pathname === "/app/notifications" ||
    /^\/app\/support(?:\/[a-zA-Z0-9-]+)?$/.test(parsed.pathname) ||
    /^\/app\/coupons(?:\/[a-zA-Z0-9-]+)?$/.test(parsed.pathname) ||
    /^\/stores\/[a-zA-Z0-9-]+$/.test(parsed.pathname) ||
    /^\/offers\/[a-zA-Z0-9-]+$/.test(parsed.pathname)
  )
    return parsed.pathname + parsed.search;
  return homePaths[role];
}
