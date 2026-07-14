"use client";

import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { MomentCapture } from "@/components/MomentCapture";
import { PostCard } from "@/components/PostCard";
import type { SerializedPost } from "@/lib/posts";

export default function MomentPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [moments, setMoments] = useState<SerializedPost[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const res = await fetch("/api/moments/today", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setUnlocked(data.unlocked);
        setMoments(data.moments);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data fetch on mount
    load();
  }, []);

  return (
    <div className="mx-auto max-w-xl px-3 pt-4">
      {!unlocked && !loading && <MomentCapture onPosted={load} />}

      {unlocked && (
        <div className="mb-4 rounded-xl bg-brand/10 px-4 py-2.5 text-sm font-medium text-brand">
          Today&apos;s Moment posted — here&apos;s everyone else&apos;s, unblurred.
        </div>
      )}

      <div className="mt-4">
        {moments.length === 0 && !loading && (
          <p className="py-10 text-center text-sm text-muted">
            No Moments yet today. Be the first.
          </p>
        )}
        <div className={!unlocked ? "pointer-events-none select-none blur-lg" : ""}>
          {moments.map((m) => (
            <PostCard key={m.id} post={m} />
          ))}
        </div>
        {!unlocked && moments.length > 0 && (
          <div className="-mt-24 flex flex-col items-center gap-2 text-center">
            <Lock size={22} className="text-muted" />
            <p className="text-sm text-muted">Post your Moment to unlock everyone else&apos;s</p>
          </div>
        )}
      </div>
    </div>
  );
}
