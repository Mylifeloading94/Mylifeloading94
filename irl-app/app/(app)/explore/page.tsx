import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { UserSearch } from "@/components/UserSearch";
import { PostsGrid } from "@/components/PostsGrid";

export default async function ExplorePage() {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const userId = session.user.id;

  const following = await prisma.follow.findMany({
    where: { followerId: userId },
    select: { followingId: true },
  });
  const excluded = [userId, ...following.map((f) => f.followingId)];

  const posts = await prisma.post.findMany({
    where: { authorId: { notIn: excluded }, closeFriendsOnly: false },
    orderBy: { createdAt: "desc" },
    take: 30,
    select: { id: true, imageUrl: true, isMoment: true, closeFriendsOnly: true },
  });

  return (
    <div className="mx-auto max-w-2xl px-3 pt-4">
      <UserSearch />
      <h2 className="mb-2 mt-6 px-1 text-sm font-semibold text-muted">Discover</h2>
      <PostsGrid posts={posts} />
    </div>
  );
}
