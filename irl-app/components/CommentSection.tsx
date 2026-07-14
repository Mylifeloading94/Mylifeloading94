"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";

type Comment = {
  id: string;
  body: string;
  createdAt: string;
  author: { id: string; username: string; name: string; avatarUrl: string | null };
};

export function CommentSection({
  postId,
  initialComments,
}: {
  postId: string;
  initialComments: Comment[];
}) {
  const [comments, setComments] = useState(initialComments);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (!body || submitting) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/posts/${postId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      if (res.ok) {
        const data = await res.json();
        setComments((prev) => [...prev, data.comment]);
        setText("");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="px-1">
      <div className="space-y-3 py-3">
        {comments.length === 0 && (
          <p className="text-sm text-muted">No comments yet. Say something real.</p>
        )}
        {comments.map((c) => (
          <div key={c.id} className="flex items-start gap-2.5">
            <Link href={`/profile/${c.author.username}`}>
              <Avatar src={c.author.avatarUrl} name={c.author.name} size={30} />
            </Link>
            <div className="text-sm">
              <Link href={`/profile/${c.author.username}`} className="mr-1.5 font-semibold">
                {c.author.username}
              </Link>
              {c.body}
              <p className="mt-0.5 text-xs text-muted" suppressHydrationWarning>{timeAgo(c.createdAt)}</p>
            </div>
          </div>
        ))}
      </div>
      <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-border py-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a comment…"
          className="flex-1 rounded-full border border-border bg-transparent px-4 py-2 text-sm outline-none focus:border-brand"
        />
        <button
          disabled={submitting || !text.trim()}
          className="text-sm font-semibold text-brand disabled:opacity-40"
        >
          Post
        </button>
      </form>
    </div>
  );
}
