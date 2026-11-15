"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import Link from "next/link";

import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, StatusBadge, Tag, fmtDateTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Alert, Paginated } from "@/lib/types";

const KIND_LABEL: Record<Alert["kind"], string> = {
  DUE_SOON: "Due soon",
  OVERDUE: "Overdue",
  LOW_STOCK: "Low stock",
  ANOMALY: "Flight data anomaly",
};

export default function AlertsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["alerts", "open"],
    queryFn: () => api<Paginated<Alert>>("/api/alerts/?resolved_at__isnull=true"),
  });
  const ack = useMutation({
    mutationFn: (id: number) => api(`/api/alerts/${id}/acknowledge/`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const run = useMutation({
    mutationFn: () => api("/api/alerts/run-check/", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <>
      <PageHeader
        title="Alerts"
        subtitle="Raised and resolved automatically by scheduled checks. Acknowledging means “seen”; fixing the cause resolves it."
        actions={
          can("ADMIN", "PLANNER") && (
            <Button onClick={() => run.mutate()} loading={run.isPending}>
              <RefreshCw aria-hidden className="size-4" /> Run due-check now
            </Button>
          )
        }
      />
      {q.isPending ? (
        <Spinner />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : q.data.results.length === 0 ? (
        <Card>
          <EmptyState>No open alerts.</EmptyState>
        </Card>
      ) : (
        <ul className="space-y-2">
          {q.data.results.map((a) => (
            <li key={a.id}>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={a.severity} />
                      <Tag>{KIND_LABEL[a.kind]}</Tag>
                      {a.aircraft && (
                        <Link href={`/aircraft/${a.aircraft}`} className="text-sm text-primary hover:underline">
                          {a.tail_number}
                        </Link>
                      )}
                    </div>
                    <p className="font-medium">{a.title}</p>
                    {a.message && <p className="text-sm text-muted">{a.message}</p>}
                    <p className="text-xs text-muted">
                      Raised {fmtDateTime(a.created_at)}
                      {a.acknowledged_by && ` · acknowledged by ${a.acknowledged_by} ${fmtDateTime(a.acknowledged_at)}`}
                    </p>
                  </div>
                  {!a.acknowledged_at && can("ADMIN", "PLANNER", "TECHNICIAN") && (
                    <Button onClick={() => ack.mutate(a.id)} loading={ack.isPending && ack.variables === a.id}>
                      Acknowledge
                    </Button>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
