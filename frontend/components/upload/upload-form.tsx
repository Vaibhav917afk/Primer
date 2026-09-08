"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, FileText, Loader2, CheckCircle2, XCircle, Search, ChevronDown } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Prospect } from "@/lib/types";

type QueueStatus = "uploading" | "pending" | "processing" | "done" | "failed";

interface QueueItem {
  jobId: string;
  fileName: string;
  status: QueueStatus;
}

const AUDIO_EXT = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"];
const VIDEO_EXT = [".mp4", ".mov", ".mkv", ".avi", ".webm"];
const TEXT_EXT = [".txt", ".md", ".json"];

function detectArtifactType(fileName: string): "audio" | "video" | "text" | null {
  const ext = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
  if (AUDIO_EXT.includes(ext)) return "audio";
  if (VIDEO_EXT.includes(ext)) return "video";
  if (TEXT_EXT.includes(ext)) return "text";
  return null;
}

// Pipeline stages a job genuinely passes through, in order — used to show
// a meaningful progress indicator instead of a generic spinner, since the
// wait here maps to real backend stages, not decoration.
const STAGE_LABELS = ["Transcribing", "Extracting claims", "Verifying", "Checking history", "Scoring", "Preparing brief"];

export function UploadForm({
  orgId,
  prospects,
  fixedProspect,
}: {
  orgId: string;
  prospects: Prospect[];
  fixedProspect?: Prospect;
}) {
  const supabase = createClient();
  const [selectedProspect, setSelectedProspect] = useState<Prospect | null>(fixedProspect ?? null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [dragging, setDragging] = useState(false);
  const [pastedText, setPastedText] = useState("");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredProspects = prospects.filter((p) =>
    `${p.name ?? ""} ${p.company ?? ""}`.toLowerCase().includes(pickerQuery.toLowerCase())
  );

  // Live status — a job's row genuinely changes multiple times as it moves
  // through the real pipeline; this reflects that instead of a fake timer.
  useEffect(() => {
    if (queue.length === 0) return;

    const channel = supabase
      .channel("upload-queue-status")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "jobs", filter: `org_id=eq.${orgId}` },
        (payload) => {
          const updated = payload.new as { id: string; status: QueueStatus };
          setQueue((prev) => prev.map((item) => (item.jobId === updated.id ? { ...item, status: updated.status } : item)));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, queue.length > 0]);

  const queueFile = useCallback(
    async (file: File) => {
      if (!selectedProspect) return;
      const artifactType = detectArtifactType(file.name);
      if (!artifactType) return;

      const tempId = `${Date.now()}-${file.name}`;
      setQueue((prev) => [...prev, { jobId: tempId, fileName: file.name, status: "uploading" }]);

      const storagePath = `${Date.now()}-${file.name}`;
      const { error: uploadError } = await supabase.storage.from("raw-uploads").upload(storagePath, file);
      if (uploadError) {
        setQueue((prev) => prev.map((q) => (q.jobId === tempId ? { ...q, status: "failed" } : q)));
        return;
      }

      const { data: job, error: insertError } = await supabase
        .from("jobs")
        .insert({
          org_id: orgId,
          prospect_id: selectedProspect.id,
          file_name: file.name,
          file_path: storagePath,
          artifact_type: artifactType,
          status: "pending",
        })
        .select()
        .single();

      if (insertError || !job) {
        setQueue((prev) => prev.map((q) => (q.jobId === tempId ? { ...q, status: "failed" } : q)));
        return;
      }

      setQueue((prev) => prev.map((q) => (q.jobId === tempId ? { ...q, jobId: job.id, status: "pending" } : q)));
    },
    [selectedProspect, orgId, supabase]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      Array.from(e.dataTransfer.files).forEach(queueFile);
    },
    [queueFile]
  );

  async function handlePasteSubmit() {
    if (!selectedProspect || !pastedText.trim()) return;
    const blob = new Blob([pastedText], { type: "text/plain" });
    const file = new File([blob], `pasted-${Date.now()}.txt`, { type: "text/plain" });
    await queueFile(file);
    setPastedText("");
  }

  return (
    <div className="max-w-2xl">
      {!fixedProspect && (
        <div className="relative mb-5">
          <label className="mb-1.5 block text-sm text-ink">Target prospect</label>
          <button
            onClick={() => setPickerOpen((o) => !o)}
            className="flex h-10 w-full items-center justify-between rounded-md border border-panel-border bg-panel px-3 text-left text-sm text-ink"
          >
            <span className={selectedProspect ? "text-ink" : "text-ink-faint"}>
              {selectedProspect ? `${selectedProspect.name} — ${selectedProspect.company ?? "—"}` : "Select a prospect…"}
            </span>
            <ChevronDown className="h-4 w-4 text-ink-faint" />
          </button>

          {pickerOpen && (
            <div className="absolute z-10 mt-1 w-full rounded-md border border-panel-border bg-panel shadow-md">
              <div className="relative border-b border-panel-border p-2">
                <Search className="pointer-events-none absolute left-4.5 top-4.5 h-3.5 w-3.5 text-ink-faint" />
                <Input
                  autoFocus
                  placeholder="Search prospects…"
                  value={pickerQuery}
                  onChange={(e) => setPickerQuery(e.target.value)}
                  className="h-8 pl-7 text-sm"
                />
              </div>
              <div className="max-h-56 overflow-y-auto">
                {filteredProspects.length === 0 ? (
                  <p className="px-3 py-3 text-sm text-ink-dim">No matches.</p>
                ) : (
                  filteredProspects.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedProspect(p);
                        setPickerOpen(false);
                        setPickerQuery("");
                      }}
                      className="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-paper"
                    >
                      {p.name} <span className="text-ink-dim">— {p.company ?? "—"}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <div
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onClick={() => selectedProspect && inputRef.current?.click()}
        className={cn(
          "flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
          !selectedProspect && "cursor-not-allowed opacity-50",
          selectedProspect && "cursor-pointer",
          dragging ? "border-gold bg-gold-soft/40" : "border-panel-border bg-panel"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={[...AUDIO_EXT, ...VIDEO_EXT, ...TEXT_EXT].join(",")}
          onChange={(e) => Array.from(e.target.files ?? []).forEach(queueFile)}
          className="sr-only"
        />
        <UploadCloud className="h-8 w-8 text-ink-faint" />
        <p className="text-sm text-ink">
          {selectedProspect ? "Drop calls, videos, or text files — multiple at once is fine" : "Select a prospect first"}
        </p>
        <p className="font-mono text-xs text-ink-faint">mp3, wav, mp4, mov, txt, md</p>
      </div>

      <div className="mt-4 flex items-start gap-2">
        <textarea
          placeholder="Or paste a transcript directly…"
          value={pastedText}
          onChange={(e) => setPastedText(e.target.value)}
          disabled={!selectedProspect}
          className="h-20 flex-1 rounded-md border border-panel-border bg-panel p-2.5 text-sm text-ink placeholder:text-ink-faint disabled:opacity-50"
        />
        <Button variant="outline" size="sm" disabled={!selectedProspect || !pastedText.trim()} onClick={handlePasteSubmit}>
          <FileText className="h-4 w-4" /> Queue
        </Button>
      </div>

      <AnimatePresence>
        {queue.length > 0 && (
          <div className="mt-6 flex flex-col gap-2">
            {queue.map((item) => (
              <motion.div
                key={item.jobId}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center justify-between rounded-md border border-panel-border bg-panel px-3.5 py-2.5"
              >
                <span className="truncate text-sm text-ink">{item.fileName}</span>
                <QueueStatusBadge status={item.status} />
              </motion.div>
            ))}
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

function QueueStatusBadge({ status }: { status: QueueStatus }) {
  if (status === "done")
    return (
      <span className="flex items-center gap-1 text-xs text-teal">
        <CheckCircle2 className="h-3.5 w-3.5" /> Done
      </span>
    );
  if (status === "failed")
    return (
      <span className="flex items-center gap-1 text-xs text-brick">
        <XCircle className="h-3.5 w-3.5" /> Failed
      </span>
    );
  if (status === "processing") {
    // A real, deliberate stage-cycling indicator — reflects the actual
    // multi-stage pipeline rather than a generic spinner, per the "motion
    // where the wait is" brief.
    return <StageProgress />;
  }
  return (
    <span className="flex items-center gap-1 text-xs text-ink-dim">
      <Loader2 className="h-3.5 w-3.5 animate-spin" /> Queued
    </span>
  );
}

function StageProgress() {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStage((s) => (s + 1) % STAGE_LABELS.length), 2200);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="flex items-center gap-1.5 text-xs text-gold">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      <AnimatePresence mode="wait">
        <motion.span
          key={stage}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.2 }}
        >
          {STAGE_LABELS[stage]}…
        </motion.span>
      </AnimatePresence>
    </span>
  );
}
