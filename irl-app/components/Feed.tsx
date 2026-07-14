"use client";

import { useState } from "react";
import type { SerializedPost } from "@/lib/posts";
import { PostCard } from "@/components/PostCard";

export function Feed({
  initialPosts,
  initialCursor,
}: {
  initialPosts: SerializedPost[];
  initialCursor: string | null;
}) {
  const [posts, setPosts] = useState(initialPosts);
  const [cursor, setCursor] = useState(initialCursor);
  const [loading, setLoading] = useState(false);

  async function loadMore() {
    if (!cursor || loading) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/feed?cursor=${cursor}`);
      const data = await res.json();
      setPosts((prev) => [...prev, ...data.posts]);
      setCursor(data.nextCursor);
    } finally {
      setLoading(false);
    }
  }

  if (posts.length === 0) {
    return (
      <div className="px-4 py-16 text-center text-muted">
        <p className="text-lg font-semibold text-foreground">Your feed is quiet</p>
        <p className="mt-1 text-sm">
          Follow people to see their posts, in order, exactly as they happened.
        </p>
      </div>
    );
  }

  return (
    <div>
      {posts.map((post) => (
        <PostCard key={post.id} post={post} />
      ))}
      {cursor && (
        <div className="flex justify-center py-6">
          <button
            onClick={loadMore}
            disabled={loading}
            className="rounded-full border border-border px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-60"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
