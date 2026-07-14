"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, username, email, password }),
    });
    const data = await res.json();

    if (!res.ok) {
      setError(data.error ?? "Something went wrong");
      setLoading(false);
      return;
    }

    const signInRes = await signIn("credentials", {
      identifier: username,
      password,
      redirect: false,
    });

    setLoading(false);
    if (signInRes?.error) {
      router.push("/login");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-black tracking-tight text-brand">IRL</h1>
          <p className="mt-2 text-sm text-muted">
            Chronological. Authentic. No vanity metrics.
          </p>
        </div>
        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-2xl border border-border bg-surface p-6"
        >
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Full name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase())}
            autoComplete="username"
            required
          />
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
          <input
            className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
            placeholder="Password (min 8 characters)"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
          {error && <p className="text-sm text-red-500">{error}</p>}
          <button
            disabled={loading}
            className="w-full rounded-lg bg-brand py-2 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-60"
          >
            {loading ? "Creating account…" : "Sign up"}
          </button>
        </form>
        <p className="mt-4 text-center text-sm text-muted">
          Already on IRL?{" "}
          <Link href="/login" className="font-semibold text-brand">
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}
