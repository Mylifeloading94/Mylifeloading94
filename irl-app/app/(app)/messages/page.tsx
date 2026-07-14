import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { listConversationsFor } from "@/lib/conversations";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";

export default async function MessagesPage() {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");

  const conversations = await listConversationsFor(session.user.id);

  return (
    <div className="mx-auto max-w-xl px-3 pt-4">
      <h1 className="mb-2 px-1 text-lg font-semibold">Messages</h1>
      {conversations.length === 0 && (
        <p className="py-16 text-center text-sm text-muted">
          No conversations yet. Visit a profile to say hi.
        </p>
      )}
      <div className="divide-y divide-border">
        {conversations.map((c) => (
          <Link
            key={c.username}
            href={`/messages/${c.username}`}
            className={`flex items-center gap-3 px-1 py-3 ${c.unread ? "bg-brand/5" : ""}`}
          >
            <Avatar src={c.avatarUrl} name={c.name} size={48} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{c.username}</p>
              <p className="truncate text-sm text-muted">{c.lastMessage ?? "Say hello"}</p>
            </div>
            <span className="shrink-0 text-xs text-muted" suppressHydrationWarning>
              {timeAgo(c.lastMessageAt)}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
