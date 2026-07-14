"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft } from "lucide-react";
import { Avatar } from "@/components/AppShell";
import { timeAgo } from "@/lib/time";

type Message = { id: string; body: string; senderId: string; createdAt: string };

export function MessageThread({
  username,
  name,
  avatarUrl,
  currentUserId,
  initialMessages,
}: {
  username: string;
  name: string;
  avatarUrl: string | null;
  currentUserId: string;
  initialMessages: Message[];
}) {
  const [messages, setMessages] = useState(initialMessages);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  useEffect(() => {
    const id = setInterval(async () => {
      const res = await fetch(`/api/messages/${username}`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages);
      }
    }, 4000);
    return () => clearInterval(id);
  }, [username]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    setText("");
    try {
      const res = await fetch(`/api/messages/${username}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [...prev, data.message]);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-1px)] max-w-xl flex-col md:h-screen">
      <div className="flex items-center gap-3 border-b border-border px-3 py-3">
        <Link href="/messages" className="md:hidden">
          <ArrowLeft size={20} />
        </Link>
        <Link href={`/profile/${username}`} className="flex items-center gap-2.5">
          <Avatar src={avatarUrl} name={name} size={36} />
          <div className="leading-tight">
            <p className="text-sm font-semibold">{username}</p>
          </div>
        </Link>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-4">
        {messages.length === 0 && (
          <p className="py-10 text-center text-sm text-muted">Say hello to {name.split(" ")[0]}.</p>
        )}
        {messages.map((m) => {
          const mine = m.senderId === currentUserId;
          return (
            <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[75%] rounded-2xl px-3.5 py-2 text-sm ${
                  mine ? "bg-brand text-white" : "bg-surface border border-border"
                }`}
              >
                {m.body}
                <div
                  className={`mt-0.5 text-[10px] ${mine ? "text-white/70" : "text-muted"}`}
                  suppressHydrationWarning
                >
                  {timeAgo(m.createdAt)}
                </div>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-border p-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Message…"
          className="flex-1 rounded-full border border-border bg-transparent px-4 py-2 text-sm outline-none focus:border-brand"
        />
        <button
          disabled={sending || !text.trim()}
          className="rounded-full bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
