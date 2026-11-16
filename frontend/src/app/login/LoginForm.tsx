"use client";

import { Plane } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Seeded by `manage.py seed_demo`. Set NEXT_PUBLIC_DEMO_LOGIN=false to hide the demo shortcuts.
export const DEMO_PASSWORD = "BakimPilot2026!";
const DEMO_ENABLED = process.env.NEXT_PUBLIC_DEMO_LOGIN !== "false";
const DEMO_ROLES = [
  { username: "admin", label: "Admin" },
  { username: "tech", label: "Technician" },
  { username: "viewer", label: "Viewer" },
] as const;

export function LoginForm() {
  const { login, user, ready } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Only allow same-site relative paths, so ?next= can't redirect to another site.
  const raw = params.get("next") ?? "/";
  const next = raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";

  useEffect(() => {
    if (ready && user) router.replace(next);
  }, [ready, user, router, next]);

  async function signIn(user: string, pass: string) {
    setError("");
    setBusy(true);
    try {
      await login(user, pass);
      router.replace(next);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Wrong username or password.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many login attempts. Wait a minute and try again.");
      else setError("Login failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    void signIn(username, password);
  }

  return (
    <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-lg border border-border bg-surface p-6" noValidate>
      <div className="flex items-center gap-2 text-lg font-semibold">
        <Plane aria-hidden className="size-6 text-primary" /> BakımPilot
      </div>
      <p className="text-sm text-muted">UAV fleet maintenance &amp; airworthiness</p>
      <Field label="Username" htmlFor="username">
        <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
      </Field>
      <Field label="Password" htmlFor="password">
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </Field>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!username || !password}>
        Log in
      </Button>
      {DEMO_ENABLED && (
        <div className="space-y-2 border-t border-border pt-4">
          <Button
            type="button"
            className="w-full"
            disabled={busy}
            onClick={() => void signIn("planner", DEMO_PASSWORD)}
          >
            Try the demo (one click)
          </Button>
          <p className="text-xs text-muted">
            Logs in as the maintenance planner. Or try another role:{" "}
            {DEMO_ROLES.map((r, i) => (
              <span key={r.username}>
                {i > 0 && " · "}
                <button
                  type="button"
                  className="underline underline-offset-2 hover:text-fg disabled:opacity-50"
                  disabled={busy}
                  onClick={() => void signIn(r.username, DEMO_PASSWORD)}
                >
                  {r.label}
                </button>
              </span>
            ))}
          </p>
          <p className="text-xs text-muted">
            Demo password for every user: <code className="font-mono">{DEMO_PASSWORD}</code>
          </p>
        </div>
      )}
    </form>
  );
}
