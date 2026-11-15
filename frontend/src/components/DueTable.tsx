"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DueItem, WorkOrder } from "@/lib/types";

import { Button, EmptyState, StatusBadge, Table, Tag, Td, Th, fmtDate, fmtNum } from "./ui";

const UNIT = { hours: "h", cycles: "cyc", days: "d" } as const;

export function DueTable({ items, hideTail = false }: { items: DueItem[]; hideTail?: boolean }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const router = useRouter();
  const create = useMutation({
    mutationFn: (key: string) => api<WorkOrder>("/api/work-orders/from-due-item/", { method: "POST", body: { key } }),
    onSuccess: (wo) => {
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      router.push(`/work-orders/${wo.id}`);
    },
  });

  if (items.length === 0) return <EmptyState>Nothing here.</EmptyState>;
  return (
    <>
      {create.error && <p role="alert" className="mb-2 text-sm text-danger">{create.error.message}</p>}
      <Table>
        <thead>
          <tr>
            <Th>Status</Th>
            {!hideTail && <Th>Aircraft</Th>}
            <Th>Task</Th>
            <Th>Remaining</Th>
            <Th>Projected due</Th>
            <Th>Last done</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.key}>
              <Td>
                <StatusBadge status={i.status} />
              </Td>
              {!hideTail && (
                <Td>
                  <Link href={`/aircraft/${i.aircraft_id}`} className="font-medium text-primary hover:underline">
                    {i.tail_number}
                  </Link>
                </Td>
              )}
              <Td>
                <div className="flex items-center gap-2">
                  {i.kind === "LIFE_LIMIT" && <Tag tone="danger">Life limit</Tag>}
                  <span>{i.title}</span>
                </div>
                {i.component_label && <p className="text-xs text-muted">{i.component_label}</p>}
              </Td>
              <Td className="tabular whitespace-nowrap">
                {i.measures.map((m) => (
                  <div key={m.unit} className={Number(m.remaining) <= 0 ? "text-danger" : undefined}>
                    {fmtNum(m.remaining)} {UNIT[m.unit]}
                    <span className="text-muted"> / {fmtNum(m.interval, 0)}</span>
                  </div>
                ))}
              </Td>
              <Td className="whitespace-nowrap">{fmtDate(i.projected_due_date)}</Td>
              <Td className="whitespace-nowrap text-muted">{fmtDate(i.last_done)}</Td>
              <Td>
                {i.kind === "RULE" && i.status !== "OK" && can("ADMIN", "PLANNER") && (
                  <Button onClick={() => create.mutate(i.key)} loading={create.isPending && create.variables === i.key}>
                    Create WO
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}
