"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Avatar } from "@/components/AppShell";

type Result = { id: string; username: string; name: string; avatarUrl: string | null; bio: string };

export function UserSearch() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear results when search box is emptied
      setResults([]);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const res = await fetch(`/api/users/search?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        setResults(data.users ?? []);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [q]);

  return (
    <div>
      <div className="flex items-center gap-2 rounded-full border border-border px-3 py-2">
        <Search size={16} className="text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search people"
          className="flex-1 bg-transparent text-sm outline-none"
        />
      </div>
      {q.trim() && (
        <div className="mt-2 divide-y divide-border rounded-xl border border-border">
          {loading && <p className="px-4 py-3 text-sm text-muted">Searching…</p>}
          {!loading && results.length === 0 && (
            <p className="px-4 py-3 text-sm text-muted">No one found.</p>
          )}
          {results.map((u) => (
            <Link
              key={u.id}
              href={`/profile/${u.username}`}
              className="flex items-center gap-3 px-4 py-2.5"
            >
              <Avatar src={u.avatarUrl} name={u.name} size={40} />
              <div className="leading-tight">
                <p className="text-sm font-semibold">{u.username}</p>
                <p className="text-sm text-muted">{u.name}</p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
