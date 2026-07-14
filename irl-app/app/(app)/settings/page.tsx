"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Avatar } from "@/components/AppShell";
import { uploadImage } from "@/lib/upload";

type Me = { username: string; name: string; bio: string; avatarUrl: string | null; email: string };

export default function SettingsPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/me")
      .then((r) => r.json())
      .then((data) => {
        setMe(data.user);
        setName(data.user.name);
        setBio(data.user.bio);
        setAvatarUrl(data.user.avatarUrl);
      });
  }, []);

  async function onAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = await uploadImage(file, "avatars");
    setAvatarUrl(url);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    const res = await fetch("/api/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, bio, avatarUrl }),
    });
    setSaving(false);
    if (res.ok) {
      setMessage("Saved");
      router.refresh();
    } else {
      setMessage("Failed to save");
    }
  }

  if (!me) return <div className="px-4 py-10 text-center text-muted">Loading…</div>;

  return (
    <div className="mx-auto max-w-md px-4 py-6">
      <h1 className="mb-5 text-xl font-bold">Edit profile</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="flex items-center gap-4">
          <Avatar src={avatarUrl} name={name} size={64} />
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              className="hidden"
              onChange={onAvatarChange}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="rounded-full border border-border px-3 py-1.5 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10"
            >
              Change photo
            </button>
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted">Bio</label>
          <textarea
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            rows={3}
            maxLength={280}
            className="w-full resize-none rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
          />
        </div>

        <div className="text-sm text-muted">@{me.username} · {me.email}</div>

        {message && <p className="text-sm text-brand">{message}</p>}

        <button
          disabled={saving}
          className="w-full rounded-lg bg-brand py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
    </div>
  );
}
