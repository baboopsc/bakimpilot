"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";

import { DueTable } from "@/components/DueTable";
import { Card, ErrorState, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { DueItem } from "@/lib/types";

const FILTERS = [
  { id: "OVERDUE,DUE_SOON", label: "Needs action" },
  { id: "OVERDUE", label: "Overdue" },
  { id: "DUE_SOON", label: "Due soon" },
  { id: "", label: "All" },
];

export default function DuePage() {
  const [filter, setFilter] = useState(FILTERS[0].id);
  const q = useQuery({
    queryKey: ["due", "list", filter],
    queryFn: () => api<DueItem[]>(`/api/due-items/${filter ? `?status=${filter}` : ""}`),
  });

  return (
    <>
      <PageHeader
        title="Due list"
        subtitle="Every maintenance task and life limit, worst first. Computed live from current hours, cycles and dates."
      />
      <div role="group" aria-label="Filter" className="mb-4 flex gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
            className={clsx(
              "cursor-pointer rounded-md px-3 py-1.5 text-sm",
              filter === f.id ? "bg-primary text-primary-fg" : "text-muted hover:bg-surface-2",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>
      <Card>{q.isPending ? <Spinner /> : q.error ? <ErrorState error={q.error} /> : <DueTable items={q.data} />}</Card>
    </>
  );
}
