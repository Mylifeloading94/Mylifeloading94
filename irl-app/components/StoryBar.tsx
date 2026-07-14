"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Plus } from "lucide-react";
import { Avatar } from "@/components/AppShell";
import { StoryViewer } from "@/components/StoryViewer";
import { uploadImage } from "@/lib/upload";

type StoryGroup = {
  author: { id: string; username: string; name: string; avatarUrl: string | null };
  stories: { id: string; imageUrl: string; createdAt: string }[];
};

export function StoryBar() {
  const { data: session } = useSession();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [groups, setGroups] = useState<StoryGroup[]>([]);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);

  async function load() {
    const res = await fetch("/api/stories", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      setGroups(data.groups ?? []);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data fetch on mount
    load();
  }, []);

  async function onAddStory(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const imageUrl = await uploadImage(file, "stories");
      await fetch("/api/stories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ imageUrl }),
      });
      await load();
    } finally {
      setUploading(false);
    }
  }

  const myId = session?.user?.id;
  const myGroupIndex = groups.findIndex((g) => g.author.id === myId);

  return (
    <div className="scrollbar-none flex gap-4 overflow-x-auto border-b border-border px-1 pb-4 pt-1">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        className="hidden"
        onChange={onAddStory}
      />
      <div className="flex shrink-0 flex-col items-center gap-1">
        <button
          onClick={() =>
            myGroupIndex >= 0 ? setViewerIndex(myGroupIndex) : fileInputRef.current?.click()
          }
          disabled={uploading}
          className="relative flex h-16 w-16 items-center justify-center rounded-full disabled:opacity-60"
          style={
            myGroupIndex >= 0
              ? { background: "linear-gradient(45deg, var(--brand), var(--brand-dark))", padding: 2 }
              : undefined
          }
        >
          <span className="flex h-full w-full items-center justify-center rounded-full bg-background">
            <Avatar
              src={session?.user?.image ?? null}
              name={session?.user?.name ?? "Me"}
              size={58}
            />
          </span>
          {myGroupIndex < 0 && (
            <span className="absolute bottom-0 right-0 flex h-5 w-5 items-center justify-center rounded-full bg-brand text-white ring-2 ring-background">
              <Plus size={13} />
            </span>
          )}
        </button>
        <span className="text-xs text-muted">Your story</span>
      </div>

      {groups
        .filter((g) => g.author.id !== myId)
        .map((g) => {
          const index = groups.indexOf(g);
          return (
            <button
              key={g.author.id}
              onClick={() => setViewerIndex(index)}
              className="flex shrink-0 flex-col items-center gap-1"
            >
              <span
                className="flex h-16 w-16 items-center justify-center rounded-full p-[2px]"
                style={{ background: "linear-gradient(45deg, var(--brand), var(--brand-dark))" }}
              >
                <span className="flex h-full w-full items-center justify-center rounded-full bg-background">
                  <Avatar src={g.author.avatarUrl} name={g.author.name} size={58} />
                </span>
              </span>
              <span className="max-w-16 truncate text-xs">{g.author.username}</span>
            </button>
          );
        })}

      {viewerIndex !== null && (
        <StoryViewer
          groups={groups}
          startGroupIndex={viewerIndex}
          onClose={() => setViewerIndex(null)}
        />
      )}
    </div>
  );
}
