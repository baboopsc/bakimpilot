"use client";

import { Plane } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username, password);
      router.replace(next);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Wrong username or password.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many login attempts. Wait a minute and try again.");
      else setError("Login failed. Try again.");
    } finally {
      setBusy(false);
    }
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
      <p className="text-xs text-muted">
        Demo users: admin, planner, tech, viewer (password <code className="font-mono">BakimPilot2026!</code>)
      </p>
    </form>
  );
}
