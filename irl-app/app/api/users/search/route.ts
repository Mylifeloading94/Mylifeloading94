import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";

export async function GET(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const q = new URL(req.url).searchParams.get("q")?.trim() ?? "";
  if (!q) return NextResponse.json({ users: [] });

  const users = await prisma.user.findMany({
    where: {
      id: { not: session.user.id },
      OR: [
        { username: { contains: q.toLowerCase() } },
        { name: { contains: q } },
      ],
    },
    select: { id: true, username: true, name: true, avatarUrl: true, bio: true },
    take: 20,
  });

  return NextResponse.json({ users });
}
