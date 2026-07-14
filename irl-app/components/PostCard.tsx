"use client";

import Link from "next/link";
import { useState } from "react";
import { Heart, MessageCircle, Lock, MapPin, BadgeCheck } from "lucide-react";
import type { SerializedPost } from "@/lib/posts";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";

export function PostCard({ post }: { post: SerializedPost }) {
  const [liked, setLiked] = useState(post.likedByMe);
  const avatars = post.likedAvatars;
  const [busy, setBusy] = useState(false);

  async function toggleLike() {
    if (busy) return;
    setBusy(true);
    const nextLiked = !liked;
    setLiked(nextLiked);
    try {
      const res = await fetch(`/api/posts/${post.id}/like`, { method: "POST" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setLiked(data.liked);
    } catch {
      setLiked(!nextLiked);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="border-b border-border py-4">
      <div className="flex items-center justify-between px-1">
        <Link href={`/profile/${post.author.username}`} className="flex items-center gap-2.5">
          <Avatar src={post.author.avatarUrl} name={post.author.name} size={36} />
          <div className="leading-tight">
            <p className="text-sm font-semibold">{post.author.username}</p>
            {post.location && (
              <p className="flex items-center gap-1 text-xs text-muted">
                <MapPin size={11} /> {post.location.placeName}
                {post.location.verified && <BadgeCheck size={11} className="text-brand" />}
              </p>
            )}
          </div>
        </Link>
        <div className="flex items-center gap-2 text-xs text-muted">
          {post.closeFriendsOnly && (
            <span className="flex items-center gap-1 rounded-full bg-brand/10 px-2 py-0.5 text-brand">
              <Lock size={11} /> Close friends
            </span>
          )}
          <span suppressHydrationWarning>{timeAgo(post.createdAt)}</span>
        </div>
      </div>

      <Link href={`/post/${post.id}`} className="mt-3 block">
        {post.isMoment && post.backImageUrl ? (
          <div className="relative mx-1 aspect-[3/4] overflow-hidden rounded-2xl bg-black">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={post.imageUrl}
              alt=""
              className="h-full w-full object-cover"
            />
            <div className="absolute left-3 top-3 h-24 w-16 overflow-hidden rounded-lg border-2 border-white shadow-lg sm:h-32 sm:w-20">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={post.backImageUrl} alt="" className="h-full w-full object-cover" />
            </div>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={post.imageUrl}
            alt=""
            className="mx-1 max-h-[600px] w-[calc(100%-0.5rem)] rounded-2xl object-cover"
          />
        )}
      </Link>

      <div className="flex items-center gap-4 px-1 pt-3">
        <button
          onClick={toggleLike}
          className={`flex items-center gap-1.5 transition-colors ${liked ? "text-brand" : "text-foreground"}`}
        >
          <Heart size={24} strokeWidth={2} fill={liked ? "currentColor" : "none"} />
        </button>
        <Link href={`/post/${post.id}`} className="flex items-center gap-1.5 text-foreground">
          <MessageCircle size={23} />
          {post.commentCount > 0 && <span className="text-sm">{post.commentCount}</span>}
        </Link>
      </div>

      <div className="px-1 pt-1.5">
        {avatars.length > 0 && (
          <div className="flex items-center gap-1.5 pb-1">
            <div className="flex -space-x-2">
              {avatars.map((a) => (
                <Avatar key={a.id} src={a.avatarUrl} name={a.name} size={18} className="border-2 border-background" />
              ))}
            </div>
            <span className="text-xs text-muted">
              liked by {avatars.map((a) => a.username).join(", ")}
              {post.likeCount !== null && post.likeCount > avatars.length
                ? ` and ${post.likeCount - avatars.length} more`
                : ""}
            </span>
          </div>
        )}
        {post.caption && (
          <p className="text-sm">
            <Link href={`/profile/${post.author.username}`} className="mr-1.5 font-semibold">
              {post.author.username}
            </Link>
            {post.caption}
          </p>
        )}
      </div>
    </article>
  );
}
