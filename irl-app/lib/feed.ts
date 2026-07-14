import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";

export async function feedWhereFor(viewerId: string): Promise<Prisma.PostWhereInput> {
  const [following, closeFriendOf] = await Promise.all([
    prisma.follow.findMany({ where: { followerId: viewerId }, select: { followingId: true } }),
    prisma.closeFriend.findMany({ where: { friendId: viewerId }, select: { ownerId: true } }),
  ]);

  const authorIds = [viewerId, ...following.map((f) => f.followingId)];
  const closeFriendAuthorIds = closeFriendOf.map((c) => c.ownerId);

  return {
    authorId: { in: authorIds },
    OR: [
      { closeFriendsOnly: false },
      { authorId: viewerId },
      { authorId: { in: closeFriendAuthorIds } },
    ],
  };
}
