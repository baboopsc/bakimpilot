import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { Assistant } from "./Assistant";

export default function AssistantPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Assistant />
    </Suspense>
  );
}
