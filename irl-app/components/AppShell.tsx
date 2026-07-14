"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import {
  Home,
  Compass,
  Camera,
  PlusSquare,
  Heart,
  Send,
  LogOut,
} from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

type Status = {
  unreadNotifications: number;
  unreadMessages: number;
  hasPostedMomentToday: boolean;
};

export function AppShell({
  username,
  name,
  avatarUrl,
  children,
}: {
  username: string;
  name: string;
  avatarUrl: string | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [status, setStatus] = useState<Status>({
    unreadNotifications: 0,
    unreadMessages: 0,
    hasPostedMomentToday: false,
  });

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const res = await fetch("/api/me/status", { cache: "no-store" });
        if (res.ok && !cancelled) setStatus(await res.json());
      } catch {
        // ignore transient network errors
      }
    }
    poll();
    const id = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pathname]);

  const items = [
    { href: "/", label: "Home", icon: Home },
    { href: "/explore", label: "Explore", icon: Compass },
    {
      href: "/moment",
      label: "Moment",
      icon: Camera,
      dot: !status.hasPostedMomentToday,
    },
    { href: "/create", label: "Create", icon: PlusSquare },
    {
      href: "/notifications",
      label: "Notifications",
      icon: Heart,
      count: status.unreadNotifications,
    },
    {
      href: "/messages",
      label: "Messages",
      icon: Send,
      count: status.unreadMessages,
    },
  ];

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-6xl">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border px-4 py-6 md:flex">
        <Link href="/" className="mb-8 px-2 text-2xl font-black tracking-tight text-brand">
          IRL
        </Link>
        <nav className="flex flex-1 flex-col gap-1">
          {items.map((item) => {
            const active = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors ${
                  active
                    ? "bg-brand/10 font-semibold text-brand"
                    : "hover:bg-black/5 dark:hover:bg-white/10"
                }`}
              >
                <span className="relative">
                  <Icon size={22} strokeWidth={active ? 2.4 : 2} />
                  {item.dot && (
                    <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-brand" />
                  )}
                  {!!item.count && (
                    <span className="absolute -right-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">
                      {item.count > 9 ? "9+" : item.count}
                    </span>
                  )}
                </span>
                {item.label}
              </Link>
            );
          })}
          <Link
            href={`/profile/${username}`}
            className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors ${
              pathname === `/profile/${username}`
                ? "bg-brand/10 font-semibold text-brand"
                : "hover:bg-black/5 dark:hover:bg-white/10"
            }`}
          >
            <Avatar src={avatarUrl} name={name} size={22} />
            Profile
          </Link>
        </nav>
        <div className="flex items-center justify-between px-2">
          <ThemeToggle />
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            aria-label="Log out"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-border hover:bg-black/5 dark:hover:bg-white/10"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background/90 px-4 py-3 backdrop-blur md:hidden">
          <Link href="/" className="text-xl font-black tracking-tight text-brand">
            IRL
          </Link>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              aria-label="Log out"
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border"
            >
              <LogOut size={16} />
            </button>
          </div>
        </header>

        <main className="flex-1 pb-20 md:pb-0">{children}</main>

        <nav className="fixed bottom-0 left-0 right-0 z-10 flex items-center justify-around border-t border-border bg-surface/95 py-2 backdrop-blur md:hidden">
          {items.map((item) => {
            const active = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative flex flex-col items-center gap-0.5 px-2 py-1 text-[10px] ${
                  active ? "text-brand" : "text-muted"
                }`}
              >
                <span className="relative">
                  <Icon size={22} strokeWidth={active ? 2.4 : 2} />
                  {item.dot && (
                    <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-brand" />
                  )}
                  {!!item.count && (
                    <span className="absolute -right-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[9px] font-bold text-white">
                      {item.count > 9 ? "9+" : item.count}
                    </span>
                  )}
                </span>
              </Link>
            );
          })}
          <Link
            href={`/profile/${username}`}
            className={`flex flex-col items-center gap-0.5 px-2 py-1 ${
              pathname === `/profile/${username}` ? "text-brand" : "text-muted"
            }`}
          >
            <Avatar src={avatarUrl} name={name} size={22} />
          </Link>
        </nav>
      </div>
    </div>
  );
}

export function Avatar({
  src,
  name,
  size = 40,
  className = "",
}: {
  src?: string | null;
  name: string;
  size?: number;
  className?: string;
}) {
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={name}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className={`shrink-0 rounded-full object-cover ${className}`}
      />
    );
  }
  return (
    <span
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      className={`flex shrink-0 items-center justify-center rounded-full bg-brand font-semibold text-white ${className}`}
    >
      {initial}
    </span>
  );
}
