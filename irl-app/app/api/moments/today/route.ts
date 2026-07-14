import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost } from "@/lib/posts";
import { todayKey } from "@/lib/date";
import { feedWhereFor } from "@/lib/feed";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const userId = session.user.id;
  const momentDate = todayKey();

  const myMoment = await prisma.post.findFirst({
    where: { authorId: userId, isMoment: true, momentDate },
  });

  const feedWhere = await feedWhereFor(userId);
  const moments = await prisma.post.findMany({
    where: { ...feedWhere, isMoment: true, momentDate },
    orderBy: { createdAt: "asc" },
    include: postCardInclude,
  });

  return NextResponse.json({
    unlocked: Boolean(myMoment),
    moments: moments.map((m) => serializePost(m, userId)),
  });
}
