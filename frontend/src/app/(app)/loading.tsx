import { Spinner } from "@/components/ui";

// Suspense boundary *below* the shared layout: client navigations between
// pages can show this immediately instead of blocking (instant navigation).
export default function Loading() {
  return <Spinner />;
}
