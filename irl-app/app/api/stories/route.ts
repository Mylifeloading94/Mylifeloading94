import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const userId = session.user.id;

  const following = await prisma.follow.findMany({
    where: { followerId: userId },
    select: { followingId: true },
  });
  const authorIds = [userId, ...following.map((f) => f.followingId)];

  const stories = await prisma.story.findMany({
    where: { authorId: { in: authorIds }, expiresAt: { gt: new Date() } },
    orderBy: { createdAt: "asc" },
    include: { author: { select: { id: true, username: true, name: true, avatarUrl: true } } },
  });

  const byAuthor = new Map<
    string,
    {
      author: { id: string; username: string; name: string; avatarUrl: string | null };
      stories: { id: string; imageUrl: string; createdAt: string }[];
    }
  >();

  for (const s of stories) {
    if (!byAuthor.has(s.authorId)) {
      byAuthor.set(s.authorId, { author: s.author, stories: [] });
    }
    byAuthor.get(s.authorId)!.stories.push({
      id: s.id,
      imageUrl: s.imageUrl,
      createdAt: s.createdAt.toISOString(),
    });
  }

  const groups = Array.from(byAuthor.values()).sort((a, b) => {
    if (a.author.id === userId) return -1;
    if (b.author.id === userId) return 1;
    const aLast = a.stories[a.stories.length - 1].createdAt;
    const bLast = b.stories[b.stories.length - 1].createdAt;
    return bLast.localeCompare(aLast);
  });

  return NextResponse.json({ groups });
}

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json().catch(() => null);
  const imageUrl = typeof body?.imageUrl === "string" ? body.imageUrl : null;
  if (!imageUrl) {
    return NextResponse.json({ error: "imageUrl is required" }, { status: 400 });
  }

  const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const story = await prisma.story.create({
    data: { authorId: session.user.id, imageUrl, expiresAt },
  });

  return NextResponse.json({ story }, { status: 201 });
}
