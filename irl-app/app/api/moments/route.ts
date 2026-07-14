import { NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost } from "@/lib/posts";
import { todayKey } from "@/lib/date";

const momentSchema = z.object({
  imageUrl: z.string().min(1),
  backImageUrl: z.string().min(1),
  caption: z.string().max(2000).default(""),
});

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const userId = session.user.id;

  const parsed = momentSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid input" },
      { status: 400 }
    );
  }

  const momentDate = todayKey();
  const existing = await prisma.post.findFirst({
    where: { authorId: userId, isMoment: true, momentDate },
  });
  if (existing) {
    return NextResponse.json({ error: "You already posted today's Moment" }, { status: 409 });
  }

  const post = await prisma.post.create({
    data: {
      authorId: userId,
      imageUrl: parsed.data.imageUrl,
      backImageUrl: parsed.data.backImageUrl,
      caption: parsed.data.caption,
      isMoment: true,
      momentDate,
    },
    include: postCardInclude,
  });

  return NextResponse.json({ post: serializePost(post, userId) }, { status: 201 });
}
