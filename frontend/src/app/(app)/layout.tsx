import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui";

// Every page in the (app) group requires a logged-in user, which is only known
// in the browser. Suspense lets Next prerender a static shell (the spinner)
// while the URL-dependent, session-dependent part renders on the client.
// These routes depend on the user's session, which only the browser knows, so
// Next can't verify them as "instant" at dev time. Opt out of that validation
// (documented approach for session-gated routes). Navigation between pages is
// still client-side and fast; loading.tsx provides the fallback (D-028).
export const instant = false;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
