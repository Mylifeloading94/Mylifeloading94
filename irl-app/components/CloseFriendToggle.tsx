"use client";

import { useState } from "react";
import { Star } from "lucide-react";

export function CloseFriendToggle({
  username,
  initialCloseFriend,
}: {
  username: string;
  initialCloseFriend: boolean;
}) {
  const [active, setActive] = useState(initialCloseFriend);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    const next = !active;
    setActive(next);
    try {
      const res = await fetch(`/api/close-friends/${username}`, { method: "POST" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setActive(data.closeFriend);
    } catch {
      setActive(!next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={active ? "Remove from close friends" : "Add to close friends"}
      className={`flex h-9 w-9 items-center justify-center rounded-full border border-border transition-colors disabled:opacity-60 ${
        active ? "text-amber-500" : "hover:bg-black/5 dark:hover:bg-white/10"
      }`}
    >
      <Star size={17} fill={active ? "currentColor" : "none"} />
    </button>
  );
}
