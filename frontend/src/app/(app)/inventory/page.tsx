"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, ErrorState, Input, PageHeader, Spinner, StatusBadge, Table, Td, Th, fmtDateTime, fmtNum } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Paginated, SparePart } from "@/lib/types";

interface Movement {
  id: number;
  part_number: string;
  delta: string;
  balance_after: string;
  reason: string;
  work_order_number: string | null;
  note: string;
  actor: string | null;
  created_at: string;
}

export default function InventoryPage() {
  const { can } = useAuth();
  const [low, setLow] = useState(false);
  const parts = useQuery({
    queryKey: ["spare-parts", low],
    queryFn: () => api<Paginated<SparePart>>(`/api/spare-parts/${qs({ low: low ? "true" : undefined })}`),
  });
  const moves = useQuery({ queryKey: ["stock-movements"], queryFn: () => api<Paginated<Movement>>("/api/stock-movements/") });

  return (
    <>
      <PageHeader
        title="Spare parts"
        subtitle="Stock changes only through recorded movements: receipts, issues to work orders, counted adjustments."
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" className="size-4" checked={low} onChange={(e) => setLow(e.target.checked)} />
            Only at reorder point
          </label>
        }
      />
      <Card className="mb-4">
        {parts.isPending ? (
          <Spinner />
        ) : parts.error ? (
          <ErrorState error={parts.error} />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Part number</Th>
                <Th>Name</Th>
                <Th>Location</Th>
                <Th className="text-right">On hand</Th>
                <Th className="text-right">Reorder at</Th>
                <Th>Stock</Th>
                {can("ADMIN", "PLANNER") && <Th>Receive</Th>}
              </tr>
            </thead>
            <tbody>
              {parts.data.results.map((p) => (
                <tr key={p.id}>
                  <Td className="font-mono text-xs">{p.part_number}</Td>
                  <Td>{p.name}</Td>
                  <Td className="text-muted">{p.location}</Td>
                  <Td className="tabular text-right">
                    {fmtNum(p.quantity_on_hand, 2)} {p.unit}
                  </Td>
                  <Td className="tabular text-right">{fmtNum(p.min_quantity, 2)}</Td>
                  <Td>{p.is_low ? <StatusBadge status={Number(p.quantity_on_hand) === 0 ? "CRITICAL" : "WARNING"} /> : <StatusBadge status="OK" />}</Td>
                  {can("ADMIN", "PLANNER") && (
                    <Td>
                      <ReceiveForm part={p} />
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card title="Recent stock movements">
        {moves.data && (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Part</Th>
                <Th className="text-right">Change</Th>
                <Th className="text-right">Balance</Th>
                <Th>Reason</Th>
                <Th>By</Th>
              </tr>
            </thead>
            <tbody>
              {moves.data.results.slice(0, 15).map((m) => (
                <tr key={m.id}>
                  <Td className="text-xs text-muted">{fmtDateTime(m.created_at)}</Td>
                  <Td className="font-mono text-xs">{m.part_number}</Td>
                  <Td className={`tabular text-right ${Number(m.delta) < 0 ? "text-warn" : "text-ok"}`}>
                    {Number(m.delta) > 0 ? "+" : ""}
                    {fmtNum(m.delta, 2)}
                  </Td>
                  <Td className="tabular text-right">{fmtNum(m.balance_after, 2)}</Td>
                  <Td>
                    {m.reason.toLowerCase()} {m.work_order_number && <span className="text-muted">· {m.work_order_number}</span>}
                  </Td>
                  <Td>{m.actor}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

function ReceiveForm({ part }: { part: SparePart }) {
  const qc = useQueryClient();
  const [qty, setQty] = useState("");
  const m = useMutation({
    mutationFn: () => api(`/api/spare-parts/${part.id}/receive/`, { method: "POST", body: { quantity: qty, note: "Goods receipt" } }),
    onSuccess: () => {
      setQty("");
      qc.invalidateQueries({ queryKey: ["spare-parts"] });
      qc.invalidateQueries({ queryKey: ["stock-movements"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  return (
    <form
      className="flex gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <Input aria-label={`Quantity received for ${part.part_number}`} type="number" min="0.01" step="0.01" value={qty} onChange={(e) => setQty(e.target.value)} className="w-20" />
      <Button type="submit" disabled={!qty || Number(qty) <= 0} loading={m.isPending}>
        +
      </Button>
    </form>
  );
}
