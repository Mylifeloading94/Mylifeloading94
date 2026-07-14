import { NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { getOrCreateConversation } from "@/lib/conversations";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ username: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { username } = await params;
  const other = await prisma.user.findUnique({ where: { username } });
  if (!other || other.id === session.user.id) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const conversation = await getOrCreateConversation(session.user.id, other.id);

  await prisma.message.updateMany({
    where: { conversationId: conversation.id, senderId: other.id, readAt: null },
    data: { readAt: new Date() },
  });

  const messages = await prisma.message.findMany({
    where: { conversationId: conversation.id },
    orderBy: { createdAt: "asc" },
  });

  return NextResponse.json({
    other: { username: other.username, name: other.name, avatarUrl: other.avatarUrl },
    messages: messages.map((m) => ({
      id: m.id,
      body: m.body,
      senderId: m.senderId,
      createdAt: m.createdAt.toISOString(),
    })),
  });
}

const sendSchema = z.object({ body: z.string().min(1).max(2000) });

export async function POST(
  req: Request,
  { params }: { params: Promise<{ username: string }> }
) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { username } = await params;
  const other = await prisma.user.findUnique({ where: { username } });
  if (!other || other.id === session.user.id) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const parsed = sendSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid input" },
      { status: 400 }
    );
  }

  const conversation = await getOrCreateConversation(session.user.id, other.id);
  const message = await prisma.message.create({
    data: { conversationId: conversation.id, senderId: session.user.id, body: parsed.data.body },
  });

  return NextResponse.json(
    {
      message: {
        id: message.id,
        body: message.body,
        senderId: message.senderId,
        createdAt: message.createdAt.toISOString(),
      },
    },
    { status: 201 }
  );
}
