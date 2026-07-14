import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { createNotification } from "@/lib/notify";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ username: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { username } = await params;

  const target = await prisma.user.findUnique({ where: { username } });
  if (!target) return NextResponse.json({ error: "Not found" }, { status: 404 });
  if (target.id === session.user.id) {
    return NextResponse.json({ error: "Cannot follow yourself" }, { status: 400 });
  }

  const existing = await prisma.follow.findUnique({
    where: {
      followerId_followingId: { followerId: session.user.id, followingId: target.id },
    },
  });

  if (existing) {
    await prisma.follow.delete({ where: { id: existing.id } });
    return NextResponse.json({ following: false });
  }

  await prisma.follow.create({
    data: { followerId: session.user.id, followingId: target.id },
  });
  await createNotification({ recipientId: target.id, actorId: session.user.id, type: "follow" });

  return NextResponse.json({ following: true });
}
