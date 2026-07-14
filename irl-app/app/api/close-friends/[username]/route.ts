import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";

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
    return NextResponse.json({ error: "Cannot add yourself" }, { status: 400 });
  }

  const existing = await prisma.closeFriend.findUnique({
    where: { ownerId_friendId: { ownerId: session.user.id, friendId: target.id } },
  });

  if (existing) {
    await prisma.closeFriend.delete({ where: { id: existing.id } });
    return NextResponse.json({ closeFriend: false });
  }

  await prisma.closeFriend.create({ data: { ownerId: session.user.id, friendId: target.id } });
  return NextResponse.json({ closeFriend: true });
}
