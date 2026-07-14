import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { UserRow } from "@/components/UserRow";

export default async function FollowingPage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const viewerId = session.user.id;

  const user = await prisma.user.findUnique({ where: { username } });
  if (!user) notFound();

  const following = await prisma.follow.findMany({
    where: { followerId: user.id },
    include: {
      following: { select: { id: true, username: true, name: true, avatarUrl: true } },
    },
    orderBy: { createdAt: "desc" },
  });

  const viewerFollowing = await prisma.follow.findMany({
    where: { followerId: viewerId, followingId: { in: following.map((f) => f.following.id) } },
    select: { followingId: true },
  });
  const followingSet = new Set(viewerFollowing.map((f) => f.followingId));

  return (
    <div className="mx-auto max-w-md pt-4">
      <h1 className="px-4 pb-2 text-lg font-semibold">Following</h1>
      {following.length === 0 && (
        <p className="px-4 py-8 text-center text-sm text-muted">Not following anyone yet.</p>
      )}
      {following.map((f) => (
        <UserRow
          key={f.following.id}
          user={f.following}
          viewerId={viewerId}
          isFollowing={followingSet.has(f.following.id)}
        />
      ))}
    </div>
  );
}
