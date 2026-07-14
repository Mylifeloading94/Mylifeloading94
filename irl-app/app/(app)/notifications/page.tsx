import Link from "next/link";
import { redirect } from "next/navigation";
import { Heart, MessageCircle, UserPlus } from "lucide-react";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";
import { MarkNotificationsRead } from "@/components/MarkNotificationsRead";

const ICONS = {
  follow: UserPlus,
  like: Heart,
  comment: MessageCircle,
};

const LABELS = {
  follow: "started following you",
  like: "liked your post",
  comment: "commented on your post",
};

export default async function NotificationsPage() {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");

  const notifications = await prisma.notification.findMany({
    where: { recipientId: session.user.id },
    orderBy: { createdAt: "desc" },
    take: 50,
    include: {
      actor: { select: { id: true, username: true, name: true, avatarUrl: true } },
      post: { select: { id: true, imageUrl: true } },
    },
  });

  return (
    <div className="mx-auto max-w-xl px-3 pt-4">
      <MarkNotificationsRead />
      <h1 className="mb-2 px-1 text-lg font-semibold">Notifications</h1>
      {notifications.length === 0 && (
        <p className="py-16 text-center text-sm text-muted">No notifications yet.</p>
      )}
      <div className="divide-y divide-border">
        {notifications.map((n) => {
          const type = n.type as keyof typeof ICONS;
          const Icon = ICONS[type] ?? Heart;
          return (
            <Link
              key={n.id}
              href={n.post ? `/post/${n.post.id}` : `/profile/${n.actor.username}`}
              className={`flex items-center gap-3 px-1 py-3 ${!n.read ? "bg-brand/5" : ""}`}
            >
              <Icon size={18} className="shrink-0 text-brand" />
              <Avatar src={n.actor.avatarUrl} name={n.actor.name} size={40} />
              <p className="flex-1 text-sm">
                <span className="font-semibold">{n.actor.username}</span>{" "}
                {LABELS[type] ?? "interacted with you"}
                <span className="ml-2 text-xs text-muted" suppressHydrationWarning>
                  {timeAgo(n.createdAt.toISOString())}
                </span>
              </p>
              {n.post && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={n.post.imageUrl} alt="" className="h-11 w-11 rounded object-cover" />
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
