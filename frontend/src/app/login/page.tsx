import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { LoginForm } from "./LoginForm";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      {/* LoginForm reads ?next=…; useSearchParams needs a Suspense boundary. */}
      <Suspense fallback={<Spinner />}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
