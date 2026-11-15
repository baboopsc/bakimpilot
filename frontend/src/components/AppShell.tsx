"use client";

import clsx from "clsx";
import {
  Bell,
  Bot,
  ClipboardList,
  FileText,
  Gauge,
  LogOut,
  Menu,
  Moon,
  Package,
  Plane,
  Sun,
  Wrench,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";

import { Spinner } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", Icon: Gauge },
  { href: "/aircraft", label: "Fleet", Icon: Plane },
  { href: "/due", label: "Due list", Icon: ClipboardList },
  { href: "/work-orders", label: "Work orders", Icon: Wrench },
  { href: "/inventory", label: "Spare parts", Icon: Package },
  { href: "/alerts", label: "Alerts", Icon: Bell },
  { href: "/assistant", label: "AI assistant", Icon: Bot },
  { href: "/manuals", label: "Manuals", Icon: FileText },
];

function readTheme(): boolean {
  try {
    return localStorage.getItem("bp-theme") === "light"; // UI preference only, nothing sensitive
  } catch {
    return false; // storage blocked: stay dark
  }
}

function ThemeToggle() {
  // AppShell only renders in the browser (after the session check), so reading storage here is safe.
  const [light, setLight] = useState(readTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = light ? "light" : "dark";
  }, [light]);
  const toggle = () => {
    const next = !light;
    setLight(next);
    try {
      localStorage.setItem("bp-theme", next ? "light" : "dark");
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      onClick={toggle}
      className="cursor-pointer rounded-md p-2 text-muted hover:bg-surface-2 hover:text-fg"
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
    >
      {light ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, ready, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [ready, user, router, pathname]);

  if (!ready || !user) return <Spinner label="Checking session…" />;

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <div className="flex min-h-screen">
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-30 flex w-60 shrink-0 flex-col border-r border-border bg-surface transition-transform duration-200 md:sticky md:top-0 md:h-screen md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <Plane aria-hidden className="size-5 text-primary" />
            BakımPilot
          </Link>
          <button className="cursor-pointer p-1 md:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="size-5" />
          </button>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 px-2">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              onClick={() => setOpen(false)}
              className={clsx(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-150",
                isActive(href) ? "bg-primary/15 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
              )}
            >
              <Icon aria-hidden className="size-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          <div className="mb-2 px-1">
            <p className="text-sm font-medium">{user.first_name ? `${user.first_name} ${user.last_name}` : user.username}</p>
            <p className="text-xs text-muted">{user.role}</p>
          </div>
          <div className="flex items-center justify-between">
            <ThemeToggle />
            <button
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted hover:bg-surface-2 hover:text-fg"
            >
              <LogOut aria-hidden className="size-4" /> Log out
            </button>
          </div>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/50 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border px-4 py-3 md:hidden">
          <button className="cursor-pointer p-1" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <span className="font-semibold">BakımPilot</span>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
