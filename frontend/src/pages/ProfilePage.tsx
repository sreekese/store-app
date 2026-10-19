import { Link } from "react-router-dom";
import ShopperProfile from "../profiles/ShopperProfile";
export default function ProfilePage() {
  return (
    <>
      <main className="container">
        <Link to="/app">Back to storefront</Link>
        <h1>My profile</h1>
        <ShopperProfile />
      </main>
    </>
  );
}
