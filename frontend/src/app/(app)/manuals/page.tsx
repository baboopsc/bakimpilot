"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Spinner, Table, Tag, Td, Th, fmtDateTime } from "@/components/ui";
import { api, openManual } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ManualDocument, Paginated } from "@/lib/types";

const STATUS_TONE = { READY: "ok", FAILED: "danger", PENDING: "info", PROCESSING: "info" } as const;

export default function ManualsPage() {
  const { can } = useAuth();
  const q = useQuery({
    queryKey: ["manuals"],
    queryFn: () => api<Paginated<ManualDocument>>("/api/ai/documents/"),
    // Keep polling while something is still being ingested in the background.
    refetchInterval: (query) =>
      query.state.data?.results.some((d) => d.status === "PENDING" || d.status === "PROCESSING") ? 2000 : false,
  });

  return (
    <>
      <PageHeader title="Maintenance manuals" subtitle="PDFs the AI assistant answers from, with page citations." />
      {can("ADMIN", "PLANNER") && <UploadForm />}
      <Card>
        {q.isPending ? (
          <Spinner />
        ) : q.error ? (
          <ErrorState error={q.error} />
        ) : q.data.results.length === 0 ? (
          <EmptyState>No manuals uploaded yet.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Title</Th>
                <Th>Model</Th>
                <Th>Status</Th>
                <Th className="text-right">Pages</Th>
                <Th className="text-right">Passages</Th>
                <Th>Uploaded</Th>
              </tr>
            </thead>
            <tbody>
              {q.data.results.map((d) => (
                <tr key={d.id}>
                  <Td>
                    <button onClick={() => openManual(d.id)} className="cursor-pointer text-left text-primary hover:underline">
                      {d.title}
                    </button>
                    {d.error && <p className="text-xs text-danger">{d.error}</p>}
                  </Td>
                  <Td>{d.aircraft_model || <span className="text-muted">All</span>}</Td>
                  <Td>
                    <Tag tone={STATUS_TONE[d.status]}>{d.status.toLowerCase()}</Tag>
                  </Td>
                  <Td className="tabular text-right">{d.page_count}</Td>
                  <Td className="tabular text-right">{d.chunk_count}</Td>
                  <Td className="text-xs text-muted">
                    {fmtDateTime(d.uploaded_at)} · {d.uploaded_by}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

function UploadForm() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [model, setModel] = useState("");
  const m = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("title", title);
      fd.append("aircraft_model", model);
      fd.append("file", fileRef.current!.files![0]);
      return api("/api/ai/documents/", { method: "POST", body: fd });
    },
    onSuccess: () => {
      setTitle("");
      setModel("");
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["manuals"] });
    },
  });
  return (
    <Card className="mb-4" title="Upload a manual">
      <form
        className="grid gap-3 md:grid-cols-4 md:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <Field label="Title" htmlFor="m-title">
          <Input id="m-title" required value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Aircraft model (optional)" htmlFor="m-model">
          <Input id="m-model" placeholder="e.g. TB2" value={model} onChange={(e) => setModel(e.target.value)} />
        </Field>
        <Field label="PDF file (max 25 MB)" htmlFor="m-file">
          <input id="m-file" ref={fileRef} type="file" accept="application/pdf" required className="block w-full text-sm" />
        </Field>
        <Button type="submit" variant="primary" loading={m.isPending} disabled={!title}>
          <Upload aria-hidden className="size-4" /> Upload
        </Button>
        {m.error && (
          <div className="md:col-span-4">
            <ErrorState error={m.error} />
          </div>
        )}
      </form>
    </Card>
  );
}
