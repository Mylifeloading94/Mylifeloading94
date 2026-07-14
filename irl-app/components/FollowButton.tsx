"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function FollowButton({
  username,
  initialFollowing,
}: {
  username: string;
  initialFollowing: boolean;
}) {
  const router = useRouter();
  const [following, setFollowing] = useState(initialFollowing);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    const next = !following;
    setFollowing(next);
    try {
      const res = await fetch(`/api/follow/${username}`, { method: "POST" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setFollowing(data.following);
      router.refresh();
    } catch {
      setFollowing(!next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors disabled:opacity-60 ${
        following
          ? "border border-border hover:bg-black/5 dark:hover:bg-white/10"
          : "bg-brand text-white hover:bg-brand-dark"
      }`}
    >
      {following ? "Following" : "Follow"}
    </button>
  );
}
