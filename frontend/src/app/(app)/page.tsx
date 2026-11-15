"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, Package, Wrench } from "lucide-react";
import Link from "next/link";

import { FlightHoursChart } from "@/components/FlightHoursChart";
import { Card, ErrorState, PageHeader, Spinner, StatusBadge, fmtDate, fmtDateTime } from "@/components/ui";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

export default function DashboardPage() {
  const { data, error, isPending } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Dashboard>("/api/dashboard/"),
    refetchInterval: 60_000, // the morning view stays current while it's open
  });

  if (isPending) return <Spinner />;
  if (error) return <ErrorState error={error} />;

  const r = data.readiness;
  const byDate = Object.entries(
    data.timeline.reduce<Record<string, Dashboard["timeline"]>>((acc, t) => {
      (acc[t.date] ??= []).push(t);
      return acc;
    }, {}),
  );

  return (
    <>
      <PageHeader title="Fleet overview" subtitle={`Updated ${fmtDateTime(data.generated_at)}`} />

      <div className="mb-6 grid gap-4 md:grid-cols-4">
        <Card className="md:col-span-1">
          <p className="text-sm text-muted">Fleet readiness</p>
          <p className="tabular mt-1 text-4xl font-semibold">{r.readiness_pct === null ? "—" : `${r.readiness_pct}%`}</p>
          <p className="mt-1 text-xs text-muted">
            {r.ready} of {r.active_aircraft} active aircraft may fly
          </p>
        </Card>
        <Card className="md:col-span-3">
          <p className="mb-3 text-sm text-muted">Aircraft status</p>
          <div className="grid gap-3 sm:grid-cols-3">
            {(["AIRWORTHY", "ATTENTION", "GROUNDED"] as const).map((s) => (
              <div key={s} className="rounded-md border border-border bg-surface-2 p-3">
                <StatusBadge status={s} />
                <p className="tabular mt-2 text-2xl font-semibold">{r.by_status[s]}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <Link href="/work-orders" className="block">
          <Card className="h-full transition-colors hover:border-muted">
            <p className="flex items-center gap-2 text-sm text-muted">
              <Wrench aria-hidden className="size-4" /> Open work orders
            </p>
            <p className="tabular mt-1 text-2xl font-semibold">
              {Object.values(data.work_orders).reduce((a, b) => a + (b ?? 0), 0)}
            </p>
            <p className="text-xs text-muted">{data.work_orders.AWAITING_INSPECTION ?? 0} awaiting inspection</p>
          </Card>
        </Link>
        <Link href="/alerts" className="block">
          <Card className="h-full transition-colors hover:border-muted">
            <p className="flex items-center gap-2 text-sm text-muted">
              <Bell aria-hidden className="size-4" /> Open alerts
            </p>
            <p className="tabular mt-1 text-2xl font-semibold">
              {Object.values(data.open_alerts).reduce((a, b) => a + (b ?? 0), 0)}
            </p>
            <p className="text-xs text-muted">{data.open_alerts.CRITICAL ?? 0} critical</p>
          </Card>
        </Link>
        <Link href="/inventory" className="block">
          <Card className="h-full transition-colors hover:border-muted">
            <p className="flex items-center gap-2 text-sm text-muted">
              <Package aria-hidden className="size-4" /> Spare parts at reorder point
            </p>
            <p className="tabular mt-1 text-2xl font-semibold">{data.low_stock}</p>
            <p className="text-xs text-muted">{data.low_stock ? "Reorder needed" : "Stock levels OK"}</p>
          </Card>
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Aircraft" className="min-w-0 lg:col-span-2">
          <ul className="divide-y divide-border">
            {data.aircraft.map((a) => (
              <li key={a.aircraft_id} className="py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <Link href={`/aircraft/${a.aircraft_id}`} className="font-medium hover:underline">
                    {a.tail_number}
                  </Link>
                  <StatusBadge status={a.status} />
                </div>
                {a.reasons.length > 0 && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{a.reasons.join(" · ")}</p>
                )}
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Maintenance timeline: next 30 days" className="min-w-0 lg:col-span-3" actions={<Link href="/due" className="text-xs text-primary hover:underline">Full due list</Link>}>
          {byDate.length === 0 ? (
            <p className="text-sm text-muted">Nothing due in the next 30 days.</p>
          ) : (
            <ol className="max-h-96 space-y-4 overflow-y-auto pr-1">
              {byDate.map(([date, items]) => (
                <li key={date}>
                  <p className="mb-1 text-xs font-semibold text-muted uppercase">{fmtDate(date)}</p>
                  <ul className="space-y-1">
                    {items.map((t) => (
                      <li key={t.key} className="flex min-w-0 items-center gap-2 text-sm">
                        <StatusBadge status={t.status} />
                        <span className="font-medium whitespace-nowrap">{t.tail_number}</span>
                        <span className="min-w-0 truncate text-muted">{t.title}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Fleet flight hours per day (last 30 days)" className="min-w-0 lg:col-span-5">
          <FlightHoursChart data={data.flight_hours_30d} />
        </Card>
      </div>
    </>
  );
}
