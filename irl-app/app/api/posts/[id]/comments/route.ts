import { NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { createNotification } from "@/lib/notify";

const commentSchema = z.object({
  body: z.string().min(1).max(1000),
});

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: postId } = await params;
  const comments = await prisma.comment.findMany({
    where: { postId },
    orderBy: { createdAt: "asc" },
    include: { author: { select: { id: true, username: true, name: true, avatarUrl: true } } },
  });
  return NextResponse.json({
    comments: comments.map((c) => ({
      id: c.id,
      body: c.body,
      createdAt: c.createdAt.toISOString(),
      author: c.author,
    })),
  });
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id: postId } = await params;

  const parsed = commentSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid input" },
      { status: 400 }
    );
  }

  const post = await prisma.post.findUnique({ where: { id: postId }, select: { authorId: true } });
  if (!post) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const comment = await prisma.comment.create({
    data: { postId, authorId: session.user.id, body: parsed.data.body },
    include: { author: { select: { id: true, username: true, name: true, avatarUrl: true } } },
  });

  await createNotification({
    recipientId: post.authorId,
    actorId: session.user.id,
    type: "comment",
    postId,
  });

  return NextResponse.json(
    {
      comment: {
        id: comment.id,
        body: comment.body,
        createdAt: comment.createdAt.toISOString(),
        author: comment.author,
      },
    },
    { status: 201 }
  );
}
