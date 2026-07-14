import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { Avatar } from "@/components/AppShell";
import { FollowButton } from "@/components/FollowButton";
import { CloseFriendToggle } from "@/components/CloseFriendToggle";
import { PostsGrid } from "@/components/PostsGrid";
import { MessageCircle, Settings } from "lucide-react";

export default async function ProfilePage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const viewerId = session.user.id;

  const user = await prisma.user.findUnique({
    where: { username },
    include: {
      _count: { select: { posts: true, followers: true, following: true } },
    },
  });
  if (!user) notFound();

  const isSelf = user.id === viewerId;

  const [isFollowing, isCloseFriend, closeFriendOfMe] = await Promise.all([
    isSelf
      ? Promise.resolve(false)
      : prisma.follow
          .findUnique({
            where: { followerId_followingId: { followerId: viewerId, followingId: user.id } },
          })
          .then(Boolean),
    isSelf
      ? Promise.resolve(false)
      : prisma.closeFriend
          .findUnique({ where: { ownerId_friendId: { ownerId: viewerId, friendId: user.id } } })
          .then(Boolean),
    isSelf
      ? Promise.resolve(false)
      : prisma.closeFriend
          .findUnique({ where: { ownerId_friendId: { ownerId: user.id, friendId: viewerId } } })
          .then(Boolean),
  ]);

  const posts = await prisma.post.findMany({
    where: {
      authorId: user.id,
      OR: [{ closeFriendsOnly: false }, { closeFriendsOnly: isSelf || closeFriendOfMe }],
    },
    orderBy: { createdAt: "desc" },
    select: { id: true, imageUrl: true, isMoment: true, closeFriendsOnly: true },
  });

  return (
    <div className="mx-auto max-w-2xl px-4 pt-6">
      <div className="flex items-center gap-6">
        <Avatar src={user.avatarUrl} name={user.name} size={84} />
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">{user.username}</h1>
            {isSelf ? (
              <Link
                href="/settings"
                className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10"
              >
                <Settings size={14} /> Edit profile
              </Link>
            ) : (
              <>
                <FollowButton username={user.username} initialFollowing={isFollowing} />
                <Link
                  href={`/messages/${user.username}`}
                  className="flex h-9 w-9 items-center justify-center rounded-full border border-border hover:bg-black/5 dark:hover:bg-white/10"
                >
                  <MessageCircle size={17} />
                </Link>
                <CloseFriendToggle username={user.username} initialCloseFriend={isCloseFriend} />
              </>
            )}
          </div>
          <div className="mt-3 flex gap-6 text-sm">
            <span>
              <strong>{user._count.posts}</strong> posts
            </span>
            <Link href={`/profile/${user.username}/followers`}>
              <strong>{user._count.followers}</strong> followers
            </Link>
            <Link href={`/profile/${user.username}/following`}>
              <strong>{user._count.following}</strong> following
            </Link>
          </div>
        </div>
      </div>
      <div className="mt-4">
        <p className="font-semibold">{user.name}</p>
        {user.bio && <p className="whitespace-pre-wrap text-sm text-muted">{user.bio}</p>}
      </div>

      <div className="mt-6 border-t border-border pt-1">
        <PostsGrid posts={posts} />
      </div>
    </div>
  );
}
