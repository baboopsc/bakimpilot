import type { WOStatus } from "@/lib/types";

import { Tag } from "./ui";

export const WO_STATUS_LABEL: Record<WOStatus, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In progress",
  AWAITING_INSPECTION: "Awaiting inspection",
  CLOSED: "Closed",
  CANCELLED: "Cancelled",
};

export function WOStatusTag({ status }: { status: WOStatus }) {
  const tone = status === "CLOSED" ? "ok" : status === "CANCELLED" ? "muted" : status === "AWAITING_INSPECTION" ? "warn" : "info";
  return <Tag tone={tone}>{WO_STATUS_LABEL[status]}</Tag>;
}
