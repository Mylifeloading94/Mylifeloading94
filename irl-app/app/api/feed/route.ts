import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost } from "@/lib/posts";
import { feedWhereFor } from "@/lib/feed";

const PAGE_SIZE = 10;

export async function GET(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const userId = session.user.id;
  const cursor = new URL(req.url).searchParams.get("cursor") ?? undefined;

  const where = await feedWhereFor(userId);

  const posts = await prisma.post.findMany({
    where,
    orderBy: { createdAt: "desc" },
    take: PAGE_SIZE + 1,
    ...(cursor ? { cursor: { id: cursor }, skip: 1 } : {}),
    include: postCardInclude,
  });

  const hasMore = posts.length > PAGE_SIZE;
  const page = posts.slice(0, PAGE_SIZE);

  return NextResponse.json({
    posts: page.map((p) => serializePost(p, userId)),
    nextCursor: hasMore ? page[page.length - 1]?.id ?? null : null,
  });
}
