import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost, canSeeCloseFriendsPost } from "@/lib/posts";
import { PostCard } from "@/components/PostCard";
import { CommentSection } from "@/components/CommentSection";

export default async function PostPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const userId = session.user.id;

  const post = await prisma.post.findUnique({ where: { id }, include: postCardInclude });
  if (!post) notFound();

  const isFollowing =
    post.authorId === userId ||
    Boolean(
      await prisma.follow.findUnique({
        where: { followerId_followingId: { followerId: userId, followingId: post.authorId } },
      })
    );
  if (!isFollowing) notFound();

  if (post.closeFriendsOnly) {
    const allowed = await canSeeCloseFriendsPost(post.authorId, userId);
    if (!allowed) notFound();
  }

  const comments = await prisma.comment.findMany({
    where: { postId: id },
    orderBy: { createdAt: "asc" },
    include: { author: { select: { id: true, username: true, name: true, avatarUrl: true } } },
  });

  return (
    <div className="mx-auto max-w-xl px-3 pt-4">
      <PostCard post={serializePost(post, userId)} />
      <CommentSection
        postId={id}
        initialComments={comments.map((c) => ({
          id: c.id,
          body: c.body,
          createdAt: c.createdAt.toISOString(),
          author: c.author,
        }))}
      />
    </div>
  );
}
