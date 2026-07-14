"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/";
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const res = await signIn("credentials", {
      identifier,
      password,
      redirect: false,
    });
    setLoading(false);
    if (res?.error) {
      setError("Invalid username/email or password");
      return;
    }
    router.push(next);
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-black tracking-tight text-brand">IRL</h1>
          <p className="mt-2 text-sm text-muted">Be a person, not a feed.</p>
        </div>
        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-2xl border border-border bg-surface p-6"
        >
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Username or email"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
          />
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          {error && <p className="text-sm text-red-500">{error}</p>}
          <button
            disabled={loading}
            className="w-full rounded-lg bg-brand py-2 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-60"
          >
            {loading ? "Logging in…" : "Log in"}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-muted">
          New here?{" "}
          <Link href="/register" className="font-semibold text-brand">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}
