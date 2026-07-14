import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { getOrCreateConversation } from "@/lib/conversations";
import { MessageThread } from "@/components/MessageThread";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ username: string }>;
}) {
  const { username } = await params;
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const userId = session.user.id;

  const other = await prisma.user.findUnique({ where: { username } });
  if (!other || other.id === userId) notFound();

  const conversation = await getOrCreateConversation(userId, other.id);

  await prisma.message.updateMany({
    where: { conversationId: conversation.id, senderId: other.id, readAt: null },
    data: { readAt: new Date() },
  });

  const messages = await prisma.message.findMany({
    where: { conversationId: conversation.id },
    orderBy: { createdAt: "asc" },
  });

  return (
    <MessageThread
      username={other.username}
      name={other.name}
      avatarUrl={other.avatarUrl}
      currentUserId={userId}
      initialMessages={messages.map((m) => ({
        id: m.id,
        body: m.body,
        senderId: m.senderId,
        createdAt: m.createdAt.toISOString(),
      }))}
    />
  );
}
