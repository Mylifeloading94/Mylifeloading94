import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";

export const postCardInclude = {
  author: {
    select: { id: true, username: true, name: true, avatarUrl: true },
  },
  likes: {
    orderBy: { createdAt: "asc" as const },
    take: 3,
    select: {
      user: { select: { id: true, username: true, name: true, avatarUrl: true } },
    },
  },
  _count: { select: { likes: true, comments: true } },
} satisfies Prisma.PostInclude;

export type PostWithRelations = Prisma.PostGetPayload<{ include: typeof postCardInclude }>;

export async function visibleAuthorIds(viewerId: string) {
  const following = await prisma.follow.findMany({
    where: { followerId: viewerId },
    select: { followingId: true },
  });
  return [viewerId, ...following.map((f) => f.followingId)];
}

export async function canSeeCloseFriendsPost(authorId: string, viewerId: string) {
  if (authorId === viewerId) return true;
  const rel = await prisma.closeFriend.findUnique({
    where: { ownerId_friendId: { ownerId: authorId, friendId: viewerId } },
  });
  return Boolean(rel);
}

export function serializePost(post: PostWithRelations, viewerId: string) {
  const likedByMe = post.likes.some((l) => l.user.id === viewerId);
  const isAuthor = post.authorId === viewerId;
  return {
    id: post.id,
    imageUrl: post.imageUrl,
    backImageUrl: post.backImageUrl,
    caption: post.caption,
    isMoment: post.isMoment,
    closeFriendsOnly: post.closeFriendsOnly,
    createdAt: post.createdAt.toISOString(),
    author: post.author,
    likedByMe,
    likedAvatars: post.likes.map((l) => l.user),
    likeCount: isAuthor ? post._count.likes : null,
    commentCount: post._count.comments,
    location: post.locationName
      ? { placeName: post.locationName, verified: post.locationVerified }
      : null,
  };
}

export type SerializedPost = ReturnType<typeof serializePost>;
