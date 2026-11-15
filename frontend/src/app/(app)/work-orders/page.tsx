"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";

import { NewWorkOrderForm } from "@/components/NewWorkOrderForm";
import { Card, EmptyState, ErrorState, PageHeader, Spinner, Table, Tag, Td, Th, fmtDate } from "@/components/ui";
import { WOStatusTag } from "@/components/WOStatusTag";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Paginated, WorkOrder } from "@/lib/types";

const FILTERS: { id: string; label: string }[] = [
  { id: "", label: "All" },
  { id: "OPEN", label: "Open" },
  { id: "IN_PROGRESS", label: "In progress" },
  { id: "AWAITING_INSPECTION", label: "Awaiting inspection" },
  { id: "CLOSED", label: "Closed" },
];

export default function WorkOrdersPage() {
  const { user, can } = useAuth();
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(user?.role === "TECHNICIAN");
  const q = useQuery({
    queryKey: ["work-orders", status, mine],
    queryFn: () => api<Paginated<WorkOrder>>(`/api/work-orders/${qs({ status, mine: mine ? "true" : undefined })}`),
  });

  return (
    <>
      <PageHeader title="Work orders" actions={can("ADMIN", "PLANNER") && <NewWorkOrderForm />} />
      <div className="mb-4 flex flex-wrap items-center gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            aria-pressed={status === f.id}
            onClick={() => setStatus(f.id)}
            className={clsx(
              "cursor-pointer rounded-md px-3 py-1.5 text-sm",
              status === f.id ? "bg-primary text-primary-fg" : "text-muted hover:bg-surface-2",
            )}
          >
            {f.label}
          </button>
        ))}
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} className="size-4" />
          Assigned to me
        </label>
      </div>
      <Card>
        {q.isPending ? (
          <Spinner />
        ) : q.error ? (
          <ErrorState error={q.error} />
        ) : q.data.results.length === 0 ? (
          <EmptyState>No work orders match.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Number</Th>
                <Th>Aircraft</Th>
                <Th>Title</Th>
                <Th>Status</Th>
                <Th>Priority</Th>
                <Th>Assignee</Th>
                <Th>Progress</Th>
                <Th>Due</Th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((w) => (
                <tr key={w.id} className="hover:bg-surface-2/50">
                  <Td>
                    <Link href={`/work-orders/${w.id}`} className="font-mono text-xs text-primary hover:underline">
                      {w.number}
                    </Link>
                  </Td>
                  <Td>{w.tail_number}</Td>
                  <Td>
                    {w.title} {w.grounding && <Tag tone="danger">Grounding</Tag>}
                  </Td>
                  <Td>
                    <WOStatusTag status={w.status} />
                  </Td>
                  <Td>
                    <Tag tone={w.priority === "AOG" || w.priority === "HIGH" ? "danger" : "muted"}>{w.priority}</Tag>
                  </Td>
                  <Td>{w.assigned_to_name ?? <span className="text-muted">Unassigned</span>}</Td>
                  <Td className="tabular">
                    {w.progress.done}/{w.progress.total}
                  </Td>
                  <Td>{fmtDate(w.due_date)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
