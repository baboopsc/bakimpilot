"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Card, ErrorState, PageHeader, Spinner, StatusBadge, Table, Td, Th, fmtDate, fmtNum } from "@/components/ui";
import { api } from "@/lib/api";
import type { Aircraft, AirworthinessStatus, Paginated } from "@/lib/types";

export default function AircraftListPage() {
  const fleet = useQuery({ queryKey: ["aircraft"], queryFn: () => api<Paginated<Aircraft>>("/api/aircraft/") });
  const aw = useQuery({ queryKey: ["airworthiness"], queryFn: () => api<AirworthinessStatus[]>("/api/airworthiness/") });

  if (fleet.isPending || aw.isPending) return <Spinner />;
  if (fleet.error || aw.error) return <ErrorState error={fleet.error ?? aw.error} />;
  const status = new Map(aw.data.map((s) => [s.aircraft_id, s]));

  return (
    <>
      <PageHeader title="Fleet" subtitle={`${fleet.data.count} aircraft`} />
      <Card>
        <Table>
          <thead>
            <tr>
              <Th>Tail</Th>
              <Th>Model</Th>
              <Th>Airworthiness</Th>
              <Th className="text-right">Hours</Th>
              <Th className="text-right">Cycles</Th>
              <Th>In service</Th>
              <Th>Why</Th>
            </tr>
          </thead>
          <tbody>
            {fleet.data.results.map((a) => {
              const s = status.get(a.id);
              return (
                <tr key={a.id} className="hover:bg-surface-2/50">
                  <Td>
                    <Link href={`/aircraft/${a.id}`} className="font-medium text-primary hover:underline">
                      {a.tail_number}
                    </Link>
                  </Td>
                  <Td>{a.model}</Td>
                  <Td>{a.status === "ACTIVE" ? s && <StatusBadge status={s.status} /> : <span className="text-muted">{a.status}</span>}</Td>
                  <Td className="tabular text-right">{fmtNum(a.total_hours)}</Td>
                  <Td className="tabular text-right">{a.total_cycles}</Td>
                  <Td>{fmtDate(a.in_service_date)}</Td>
                  <Td className="max-w-md text-xs text-muted">{s?.reasons.slice(0, 2).join(" · ")}</Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>
    </>
  );
}
