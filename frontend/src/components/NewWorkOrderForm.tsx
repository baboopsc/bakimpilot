"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";
import type { Aircraft, Paginated, User, WorkOrder } from "@/lib/types";

import { Button, ErrorState, Field, Input } from "./ui";

const selectCls = "min-h-9 w-full rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm";

/** Ad-hoc work order (e.g. a defect found on walk-around). Rule-based ones come from the due list. */
export function NewWorkOrderForm() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const router = useRouter();
  const [form, setForm] = useState({ aircraft: "", title: "", grounding: false, priority: "NORMAL", assigned_to: "", checklist: "" });
  const aircraft = useQuery({ queryKey: ["aircraft"], queryFn: () => api<Paginated<Aircraft>>("/api/aircraft/"), enabled: open });
  const techs = useQuery({
    queryKey: ["technicians"],
    queryFn: () => api<User[]>("/api/technicians/"),
    enabled: open,
  });
  const m = useMutation({
    mutationFn: () =>
      api<WorkOrder>("/api/work-orders/", {
        method: "POST",
        body: {
          aircraft: Number(form.aircraft),
          title: form.title,
          grounding: form.grounding,
          priority: form.priority,
          assigned_to: form.assigned_to ? Number(form.assigned_to) : null,
          checklist_items: form.checklist.split("\n").map((s) => s.trim()).filter(Boolean),
        },
      }),
    onSuccess: (wo) => {
      qc.invalidateQueries();
      router.push(`/work-orders/${wo.id}`);
    },
  });

  if (!open)
    return (
      <Button variant="primary" onClick={() => setOpen(true)}>
        <Plus aria-hidden className="size-4" /> New work order
      </Button>
    );

  return (
    <form
      className="fixed inset-x-4 top-20 z-40 mx-auto max-w-lg space-y-3 rounded-lg border border-border bg-surface p-5 shadow-2xl"
      aria-label="New work order"
      onSubmit={(e) => {
        e.preventDefault();
        m.mutate();
      }}
    >
      <h2 className="font-semibold">New work order</h2>
      <Field label="Aircraft" htmlFor="wo-aircraft">
        <select id="wo-aircraft" className={selectCls} required value={form.aircraft} onChange={(e) => setForm({ ...form, aircraft: e.target.value })}>
          <option value="">Select…</option>
          {aircraft.data?.results.map((a) => (
            <option key={a.id} value={a.id}>
              {a.tail_number}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Title" htmlFor="wo-title">
        <Input id="wo-title" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Priority" htmlFor="wo-priority">
          <select id="wo-priority" className={selectCls} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {["LOW", "NORMAL", "HIGH", "AOG"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        {techs.data && (
          <Field label="Technician" htmlFor="wo-tech">
            <select id="wo-tech" className={selectCls} value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}>
              <option value="">Unassigned</option>
              {techs.data.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.first_name ? `${t.first_name} ${t.last_name}` : t.username}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <Field label="Checklist (one item per line)" htmlFor="wo-checklist">
        <textarea
          id="wo-checklist"
          rows={4}
          className={selectCls}
          value={form.checklist}
          onChange={(e) => setForm({ ...form, checklist: e.target.value })}
        />
      </Field>
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <input type="checkbox" className="size-4" checked={form.grounding} onChange={(e) => setForm({ ...form, grounding: e.target.checked })} />
        Grounding: the aircraft may not fly until this is closed
      </label>
      {m.error && <ErrorState error={m.error} />}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={m.isPending}>
          Create
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
