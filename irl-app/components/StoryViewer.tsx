"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";

type StoryGroup = {
  author: { id: string; username: string; name: string; avatarUrl: string | null };
  stories: { id: string; imageUrl: string; createdAt: string }[];
};

const DURATION_MS = 5000;

export function StoryViewer({
  groups,
  startGroupIndex,
  onClose,
}: {
  groups: StoryGroup[];
  startGroupIndex: number;
  onClose: () => void;
}) {
  const [groupIndex, setGroupIndex] = useState(startGroupIndex);
  const [storyIndex, setStoryIndex] = useState(0);
  const [progress, setProgress] = useState(0);

  const group = groups[groupIndex];
  const story = group?.stories[storyIndex];

  useEffect(() => {
    if (!story) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset progress bar for new story
    setProgress(0);
    const start = Date.now();
    const interval = setInterval(() => {
      const pct = Math.min(100, ((Date.now() - start) / DURATION_MS) * 100);
      setProgress(pct);
      if (pct >= 100) {
        clearInterval(interval);
        goNext();
      }
    }, 50);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupIndex, storyIndex]);

  function goNext() {
    if (!group) return;
    if (storyIndex + 1 < group.stories.length) {
      setStoryIndex(storyIndex + 1);
    } else if (groupIndex + 1 < groups.length) {
      setGroupIndex(groupIndex + 1);
      setStoryIndex(0);
    } else {
      onClose();
    }
  }

  function goPrev() {
    if (storyIndex > 0) {
      setStoryIndex(storyIndex - 1);
    } else if (groupIndex > 0) {
      setGroupIndex(groupIndex - 1);
      setStoryIndex(groups[groupIndex - 1].stories.length - 1);
    }
  }

  if (!group || !story) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black">
      <div className="relative flex h-full w-full max-w-md flex-col">
        <div className="absolute left-0 right-0 top-0 z-10 flex gap-1 p-2">
          {group.stories.map((s, i) => (
            <div key={s.id} className="h-0.5 flex-1 overflow-hidden rounded-full bg-white/30">
              <div
                className="h-full bg-white"
                style={{
                  width: i < storyIndex ? "100%" : i === storyIndex ? `${progress}%` : "0%",
                }}
              />
            </div>
          ))}
        </div>
        <div className="absolute left-0 right-0 top-4 z-10 flex items-center justify-between px-3 pt-2">
          <div className="flex items-center gap-2">
            <Avatar src={group.author.avatarUrl} name={group.author.name} size={30} />
            <span className="text-sm font-semibold text-white">{group.author.username}</span>
            <span className="text-xs text-white/70">{timeAgo(story.createdAt)}</span>
          </div>
          <button onClick={onClose} className="text-white">
            <X size={22} />
          </button>
        </div>

        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={story.imageUrl} alt="" className="h-full w-full object-contain" />

        <button
          onClick={goPrev}
          aria-label="Previous"
          className="absolute left-0 top-0 h-full w-1/3"
        />
        <button
          onClick={goNext}
          aria-label="Next"
          className="absolute right-0 top-0 h-full w-1/3"
        />
      </div>
    </div>
  );
}
