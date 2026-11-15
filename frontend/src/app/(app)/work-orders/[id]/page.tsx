"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckSquare, ShieldCheck, ShieldX, Square } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { WOStatusTag } from "@/components/WOStatusTag";
import { Button, Card, ErrorState, Field, Input, PageHeader, Spinner, Tag, fmtDateTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AuditEntry, User, WorkOrder } from "@/lib/types";

export default function WorkOrderPage() {
  const { id } = useParams<{ id: string }>();
  const { user, can } = useAuth();
  const qc = useQueryClient();
  const key = ["work-orders", "detail", id];
  const wo = useQuery({ queryKey: key, queryFn: () => api<WorkOrder>(`/api/work-orders/${id}/`) });
  const history = useQuery({
    queryKey: [...key, "history"],
    queryFn: () => api<AuditEntry[]>(`/api/work-orders/${id}/history/`),
  });
  const verify = useQuery({
    queryKey: [...key, "verify"],
    queryFn: () => api<{ signatures_valid: boolean }>(`/api/work-orders/${id}/verify/`),
    enabled: !!wo.data?.tech_signature,
  });

  // Every action returns the updated work order; refresh everything that depends on it.
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      api<WorkOrder>(`/api/work-orders/${id}/${path}/`, { method: "POST", body }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["work-orders"], exact: false });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["due"] });
    },
  });

  if (wo.isPending) return <Spinner />;
  if (wo.error) return <ErrorState error={wo.error} />;
  const w = wo.data;
  const isAssignee = user?.id === w.assigned_to;
  const isInspector = can("ADMIN", "PLANNER");
  const allDone = w.checklist.every((i) => i.done);
  const editable = w.status === "IN_PROGRESS" && isAssignee;

  return (
    <>
      <PageHeader
        title={`${w.number} · ${w.title}`}
        subtitle={
          <>
            <Link href={`/aircraft/${w.aircraft}`} className="text-primary hover:underline">
              {w.tail_number}
            </Link>{" "}
            · created by {w.created_by} {fmtDateTime(w.created_at)}
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            {w.grounding && <Tag tone="danger">Grounding</Tag>}
            <Tag tone={w.priority === "AOG" || w.priority === "HIGH" ? "danger" : "muted"}>{w.priority}</Tag>
            <WOStatusTag status={w.status} />
          </div>
        }
      />
      {act.error && (
        <div className="mb-4">
          <ErrorState error={act.error} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {w.description && (
            <Card>
              <p className="text-sm whitespace-pre-line">{w.description}</p>
            </Card>
          )}

          <Card title={`Checklist (${w.progress.done}/${w.progress.total})`}>
            {w.checklist.length === 0 && <p className="text-sm text-muted">No checklist items.</p>}
            <ol className="space-y-2">
              {w.checklist.map((item) => (
                <ChecklistRow
                  key={item.id}
                  item={item}
                  editable={editable}
                  busy={act.isPending}
                  onChange={(done, note) => act.mutate({ path: "checklist", body: { item: item.id, done, note } })}
                />
              ))}
            </ol>
          </Card>

          <Card title="Sign-off">
            <Signatures w={w} valid={verify.data?.signatures_valid} />
            <div className="mt-4 space-y-3">
              {w.status === "OPEN" && isAssignee && (
                <Button variant="primary" onClick={() => act.mutate({ path: "start" })} loading={act.isPending}>
                  Start work
                </Button>
              )}
              {w.status === "OPEN" && !w.assigned_to && <p className="text-sm text-muted">Assign a technician to start.</p>}
              {w.status === "IN_PROGRESS" && isAssignee && (
                <PasswordAction
                  label="Sign off as technician"
                  disabled={!allDone}
                  hint={allDone ? "Re-enter your password to sign. This is your digital signature." : "Complete every checklist item first."}
                  busy={act.isPending}
                  onConfirm={(password) => act.mutate({ path: "sign-off", body: { password } })}
                />
              )}
              {w.status === "AWAITING_INSPECTION" && isInspector && user?.username !== w.tech_signed_by && (
                <>
                  <PasswordAction
                    label="Certify & close"
                    hint="Independent inspection: you confirm the work was done correctly. Closing records the maintenance task."
                    busy={act.isPending}
                    onConfirm={(password) => act.mutate({ path: "certify", body: { password } })}
                  />
                  <ReasonAction label="Reject: send back to technician" busy={act.isPending} onConfirm={(reason) => act.mutate({ path: "reject", body: { reason } })} />
                </>
              )}
              {w.status === "AWAITING_INSPECTION" && isInspector && user?.username === w.tech_signed_by && (
                <p className="text-sm text-warn">You signed this work, so another inspector must certify it (two-person rule).</p>
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          {isInspector && ["OPEN", "IN_PROGRESS"].includes(w.status) && (
            <Card title="Planning">
              <AssignForm current={w.assigned_to} busy={act.isPending} onAssign={(technician) => act.mutate({ path: "assign", body: { technician } })} />
              <div className="mt-4">
                <ReasonAction label="Cancel work order" danger busy={act.isPending} onConfirm={(reason) => act.mutate({ path: "cancel", body: { reason } })} />
              </div>
            </Card>
          )}
          <Card title="Audit trail">
            {history.data ? (
              <ol className="space-y-3">
                {history.data.map((e) => (
                  <li key={e.id} className="text-sm">
                    <p className="text-xs text-muted">
                      {fmtDateTime(e.timestamp)} · {e.actor ?? "system"}
                    </p>
                    <p>{e.summary}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <Spinner />
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function ChecklistRow({
  item,
  editable,
  busy,
  onChange,
}: {
  item: WorkOrder["checklist"][number];
  editable: boolean;
  busy: boolean;
  onChange: (done: boolean, note: string) => void;
}) {
  const [note, setNote] = useState(item.note);
  const Icon = item.done ? CheckSquare : Square;
  return (
    <li className={clsx("rounded-md border border-border p-3", item.done && "bg-ok/5")}>
      <div className="flex items-start gap-3">
        <button
          disabled={!editable || busy}
          onClick={() => onChange(!item.done, note)}
          aria-pressed={item.done}
          aria-label={`${item.done ? "Mark not done" : "Mark done"}: ${item.text}`}
          className="mt-0.5 cursor-pointer disabled:cursor-default"
        >
          <Icon aria-hidden className={clsx("size-5", item.done ? "text-ok" : "text-muted")} />
        </button>
        <div className="flex-1">
          <p className="text-sm">
            <span className="mr-2 text-muted tabular">{item.position}.</span>
            {item.text}
          </p>
          {item.done && (
            <p className="mt-1 text-xs text-muted">
              {item.done_by} · {fmtDateTime(item.done_at)}
            </p>
          )}
          {editable ? (
            <Input
              className="mt-2"
              placeholder="Finding / measured value (optional)"
              aria-label={`Note for item ${item.position}`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={() => note !== item.note && item.done && onChange(true, note)}
            />
          ) : (
            item.note && <p className="mt-1 text-sm text-muted">“{item.note}”</p>
          )}
        </div>
      </div>
    </li>
  );
}

function Signatures({ w, valid }: { w: WorkOrder; valid?: boolean }) {
  const rows = [
    { label: "Technician", by: w.tech_signed_by, at: w.tech_signed_at, sig: w.tech_signature },
    { label: "Inspector", by: w.inspector_signed_by, at: w.inspector_signed_at, sig: w.inspector_signature },
  ];
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="w-24 text-muted">{r.label}</span>
          {r.by ? (
            <>
              <span className="font-medium">{r.by}</span>
              <span className="text-muted">{fmtDateTime(r.at)}</span>
              <code className="truncate font-mono text-xs text-muted" title={r.sig}>
                sha256:{r.sig.slice(0, 16)}…
              </code>
            </>
          ) : (
            <span className="text-muted">not signed</span>
          )}
        </div>
      ))}
      {valid !== undefined && (
        <p className={clsx("flex items-center gap-1 text-sm", valid ? "text-ok" : "text-danger")}>
          {valid ? <ShieldCheck aria-hidden className="size-4" /> : <ShieldX aria-hidden className="size-4" />}
          {valid ? "Signed content unchanged" : "Content changed after signing!"}
        </p>
      )}
    </div>
  );
}

function PasswordAction({
  label,
  hint,
  disabled,
  busy,
  onConfirm,
}: {
  label: string;
  hint: string;
  disabled?: boolean;
  busy: boolean;
  onConfirm: (password: string) => void;
}) {
  const [password, setPassword] = useState("");
  const fieldId = `pw-${label.replace(/\W/g, "")}`;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onConfirm(password);
        setPassword("");
      }}
    >
      <div className="min-w-56 flex-1">
        <Field label="Password" htmlFor={fieldId} hint={hint}>
          <Input id={fieldId} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={disabled} />
        </Field>
      </div>
      <Button type="submit" variant="primary" disabled={disabled || !password} loading={busy} className="mb-5">
        {label}
      </Button>
    </form>
  );
}

function ReasonAction({ label, danger, busy, onConfirm }: { label: string; danger?: boolean; busy: boolean; onConfirm: (reason: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open)
    return (
      <Button variant={danger ? "ghost" : "secondary"} onClick={() => setOpen(true)}>
        {label}
      </Button>
    );
  return (
    <form
      className="flex flex-wrap gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onConfirm(reason);
        setOpen(false);
      }}
    >
      <Input aria-label="Reason" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1" autoFocus />
      <Button type="submit" variant={danger ? "danger" : "secondary"} disabled={!reason.trim()} loading={busy}>
        Confirm
      </Button>
      <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
        Back
      </Button>
    </form>
  );
}

function AssignForm({ current, busy, onAssign }: { current: number | null; busy: boolean; onAssign: (id: number) => void }) {
  const techs = useQuery({ queryKey: ["technicians"], queryFn: () => api<User[]>("/api/technicians/") });
  const [sel, setSel] = useState(current ? String(current) : "");
  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (sel) onAssign(Number(sel));
      }}
    >
      <div className="flex-1">
        <Field label="Assigned technician" htmlFor="assign">
          <select id="assign" className="min-h-9 w-full rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm" value={sel} onChange={(e) => setSel(e.target.value)}>
            <option value="">Select…</option>
            {techs.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.first_name ? `${t.first_name} ${t.last_name}` : t.username}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Button type="submit" disabled={!sel || Number(sel) === current} loading={busy}>
        Assign
      </Button>
    </form>
  );
}
