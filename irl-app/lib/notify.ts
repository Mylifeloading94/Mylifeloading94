import { prisma } from "@/lib/prisma";

export async function createNotification({
  recipientId,
  actorId,
  type,
  postId,
}: {
  recipientId: string;
  actorId: string;
  type: "follow" | "like" | "comment";
  postId?: string;
}) {
  if (recipientId === actorId) return;
  await prisma.notification.create({
    data: { recipientId, actorId, type, postId },
  });
}
