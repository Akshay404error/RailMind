import { useEffect, useState } from "react";
import { fetchMe, logout } from "../auth";

// Shows "name - Sign out". Put it in your header.
export default function AccountBar() {
  const [me, setMe] = useState(null);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => {});
  }, []);

  if (!me) return null;
  return (
    <div className="account-bar">
      <span title={me.email}>{me.name}{me.is_admin ? " (admin)" : ""}</span>
      <button className="chip" onClick={logout}>Sign out</button>
    </div>
  );
}