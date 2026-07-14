import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { createNotification } from "@/lib/notify";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id: postId } = await params;
  const userId = session.user.id;

  const post = await prisma.post.findUnique({ where: { id: postId }, select: { authorId: true } });
  if (!post) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const existing = await prisma.like.findUnique({
    where: { postId_userId: { postId, userId } },
  });

  if (existing) {
    await prisma.like.delete({ where: { id: existing.id } });
    return NextResponse.json({ liked: false });
  }

  await prisma.like.create({ data: { postId, userId } });
  await createNotification({
    recipientId: post.authorId,
    actorId: userId,
    type: "like",
    postId,
  });
  return NextResponse.json({ liked: true });
}
