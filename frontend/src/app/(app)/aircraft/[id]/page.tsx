"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { DueTable } from "@/components/DueTable";
import {
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Spinner,
  StatusBadge,
  Table,
  Td,
  Th,
  fmtDateTime,
  fmtNum,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Aircraft, AirworthinessStatus, Anomaly, DueItem, Flight, Installation, Paginated } from "@/lib/types";

export default function AircraftDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const ac = useQuery({ queryKey: ["aircraft", id], queryFn: () => api<Aircraft>(`/api/aircraft/${id}/`) });
  const aw = useQuery({
    queryKey: ["airworthiness", id],
    queryFn: () => api<AirworthinessStatus[]>(`/api/airworthiness/?aircraft=${id}`),
  });
  const comps = useQuery({ queryKey: ["aircraft", id, "components"], queryFn: () => api<Installation[]>(`/api/aircraft/${id}/components/`) });
  const due = useQuery({ queryKey: ["due", id], queryFn: () => api<DueItem[]>(`/api/due-items/?aircraft=${id}`) });
  const flights = useQuery({
    queryKey: ["flights", id],
    queryFn: () => api<Paginated<Flight>>(`/api/flights/?aircraft=${id}`),
  });
  const anomalies = useQuery({ queryKey: ["anomalies", id], queryFn: () => api<Anomaly[]>(`/api/ai/anomalies/?aircraft=${id}`) });

  if (ac.isPending) return <Spinner />;
  if (ac.error) return <ErrorState error={ac.error} />;
  const status = aw.data?.[0];

  return (
    <>
      <PageHeader
        title={ac.data.tail_number}
        subtitle={`${ac.data.model} · S/N ${ac.data.serial_number} · ${fmtNum(ac.data.total_hours)} h · ${ac.data.total_cycles} cycles`}
        actions={status && <StatusBadge status={status.status} />}
      />

      {status && status.reasons.length > 0 && (
        <Card className="mb-4">
          <ul className="list-inside list-disc space-y-1 text-sm">
            {status.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Card>
      )}

      {anomalies.data && anomalies.data.length > 0 && (
        <Card className="mb-4 border-warn/50" title={<span className="flex items-center gap-2 text-warn"><Activity aria-hidden className="size-4" /> Flight data anomaly</span>}>
          {anomalies.data.map((a) => (
            <p key={a.key} className="text-sm">
              <strong>{a.label}</strong> is unusually {a.direction}: last flights{" "}
              <span className="tabular">{a.recent_values.join(", ")}</span> {a.unit} vs normal {a.baseline_median} {a.unit}.{" "}
              <Link href={`/assistant?tab=anomalies`} className="text-primary hover:underline">
                Explain with AI
              </Link>
            </p>
          ))}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Due items" className="lg:col-span-2">
          {due.isPending ? <Spinner /> : due.error ? <ErrorState error={due.error} /> : <DueTable items={due.data} hideTail />}
        </Card>

        <Card title="Installed components">
          {comps.data && (
            <Table>
              <thead>
                <tr>
                  <Th>Position</Th>
                  <Th>Component</Th>
                  <Th>Installed</Th>
                </tr>
              </thead>
              <tbody>
                {comps.data.map((c) => (
                  <tr key={c.id}>
                    <Td className="font-mono text-xs">{c.position}</Td>
                    <Td>{c.component_label}</Td>
                    <Td className="text-xs text-muted">{fmtDateTime(c.installed_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card title="Recent flights">
          {can("ADMIN", "PLANNER", "TECHNICIAN") && ac.data.status === "ACTIVE" && <LogFlightForm aircraftId={ac.data.id} />}
          {flights.data && (
            <Table>
              <thead>
                <tr>
                  <Th>Take-off</Th>
                  <Th className="text-right">Hours</Th>
                  <Th className="text-right">Vib. g</Th>
                  <Th className="text-right">Temp °C</Th>
                </tr>
              </thead>
              <tbody>
                {flights.data.results.slice(0, 10).map((f) => (
                  <tr key={f.id}>
                    <Td>{fmtDateTime(f.takeoff_at)}</Td>
                    <Td className="tabular text-right">{f.duration_hours}</Td>
                    <Td className="tabular text-right">{f.avg_vibration_g ?? "—"}</Td>
                    <Td className="tabular text-right">{f.max_engine_temp_c ?? "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}

function toLocalInput(d: Date) {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 16);
}

function LogFlightForm({ aircraftId }: { aircraftId: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const now = new Date();
  const [takeoff, setTakeoff] = useState(toLocalInput(new Date(now.getTime() - 2 * 3600_000)));
  const [landing, setLanding] = useState(toLocalInput(now));
  const [cycles, setCycles] = useState("1");
  const m = useMutation({
    mutationFn: () =>
      api("/api/flights/", {
        method: "POST",
        body: {
          aircraft: aircraftId,
          takeoff_at: new Date(takeoff).toISOString(),
          landing_at: new Date(landing).toISOString(),
          cycles: Number(cycles),
        },
      }),
    onSuccess: () => {
      // A flight changes counters → due items, status and dashboard all move.
      qc.invalidateQueries();
      setOpen(false);
    },
  });

  if (!open)
    return (
      <Button className="mb-3" onClick={() => setOpen(true)}>
        Log flight
      </Button>
    );
  return (
    <form
      className="mb-4 grid gap-3 rounded-md border border-border p-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <Field label="Take-off" htmlFor="takeoff">
        <Input id="takeoff" type="datetime-local" value={takeoff} onChange={(e) => setTakeoff(e.target.value)} required />
      </Field>
      <Field label="Landing" htmlFor="landing">
        <Input id="landing" type="datetime-local" value={landing} onChange={(e) => setLanding(e.target.value)} required />
      </Field>
      <Field label="Cycles" htmlFor="cycles">
        <Input id="cycles" type="number" min={1} value={cycles} onChange={(e) => setCycles(e.target.value)} required />
      </Field>
      {m.error && <div className="sm:col-span-3"><ErrorState error={m.error} /></div>}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" variant="primary" loading={m.isPending}>
          Save flight
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
