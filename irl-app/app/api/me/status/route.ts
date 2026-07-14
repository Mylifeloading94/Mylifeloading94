import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { todayKey } from "@/lib/date";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const userId = session.user.id;

  const [unreadNotifications, unreadConversations, momentToday] = await Promise.all([
    prisma.notification.count({ where: { recipientId: userId, read: false } }),
    prisma.conversationParticipant.findMany({
      where: { userId },
      select: {
        conversation: {
          select: {
            messages: {
              orderBy: { createdAt: "desc" },
              take: 1,
              select: { senderId: true, readAt: true },
            },
          },
        },
      },
    }),
    prisma.post.findFirst({
      where: { authorId: userId, isMoment: true, momentDate: todayKey() },
      select: { id: true },
    }),
  ]);

  const unreadMessages = unreadConversations.filter((c) => {
    const last = c.conversation.messages[0];
    return last && last.senderId !== userId && !last.readAt;
  }).length;

  return NextResponse.json({
    unreadNotifications,
    unreadMessages,
    hasPostedMomentToday: Boolean(momentToday),
  });
}
