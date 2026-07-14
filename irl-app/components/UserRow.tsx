import Link from "next/link";
import { Avatar } from "@/components/AppShell";
import { FollowButton } from "@/components/FollowButton";

export function UserRow({
  user,
  viewerId,
  isFollowing,
}: {
  user: { id: string; username: string; name: string; avatarUrl: string | null; bio?: string };
  viewerId: string;
  isFollowing: boolean;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5">
      <Link href={`/profile/${user.username}`} className="flex items-center gap-3">
        <Avatar src={user.avatarUrl} name={user.name} size={44} />
        <div className="leading-tight">
          <p className="text-sm font-semibold">{user.username}</p>
          <p className="text-sm text-muted">{user.name}</p>
        </div>
      </Link>
      {user.id !== viewerId && (
        <FollowButton username={user.username} initialFollowing={isFollowing} />
      )}
    </div>
  );
}
