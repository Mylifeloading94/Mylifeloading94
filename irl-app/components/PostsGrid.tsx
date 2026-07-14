import Link from "next/link";
import { Camera, Lock } from "lucide-react";

export function PostsGrid({
  posts,
}: {
  posts: { id: string; imageUrl: string; isMoment: boolean; closeFriendsOnly: boolean }[];
}) {
  if (posts.length === 0) {
    return <p className="px-4 py-12 text-center text-sm text-muted">No posts yet.</p>;
  }
  return (
    <div className="grid grid-cols-3 gap-0.5">
      {posts.map((post) => (
        <Link key={post.id} href={`/post/${post.id}`} className="relative aspect-square">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={post.imageUrl} alt="" className="h-full w-full object-cover" />
          {(post.isMoment || post.closeFriendsOnly) && (
            <span className="absolute right-1.5 top-1.5 text-white drop-shadow">
              {post.isMoment ? <Camera size={15} /> : <Lock size={15} />}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}
