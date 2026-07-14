import { prisma } from "@/lib/prisma";

export async function listConversationsFor(userId: string) {
  const participations = await prisma.conversationParticipant.findMany({
    where: { userId },
    include: {
      conversation: {
        include: {
          participants: {
            where: { userId: { not: userId } },
            include: { user: { select: { id: true, username: true, name: true, avatarUrl: true } } },
          },
          messages: { orderBy: { createdAt: "desc" }, take: 1 },
        },
      },
    },
  });

  return participations
    .filter((p) => p.conversation.participants.length > 0)
    .map((p) => {
      const other = p.conversation.participants[0].user;
      const last = p.conversation.messages[0];
      return {
        username: other.username,
        name: other.name,
        avatarUrl: other.avatarUrl,
        lastMessage: last ? last.body : null,
        lastMessageAt: last ? last.createdAt.toISOString() : p.conversation.createdAt.toISOString(),
        unread: Boolean(last && last.senderId !== userId && !last.readAt),
      };
    })
    .sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt));
}

export async function getOrCreateConversation(userA: string, userB: string) {
  const existing = await prisma.conversation.findFirst({
    where: {
      participants: { some: { userId: userA } },
      AND: { participants: { some: { userId: userB } } },
    },
    include: { participants: true },
  });
  if (existing && existing.participants.length === 2) return existing;

  return prisma.conversation.create({
    data: { participants: { create: [{ userId: userA }, { userId: userB }] } },
    include: { participants: true },
  });
}
