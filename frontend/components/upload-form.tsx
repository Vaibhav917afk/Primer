"use client";

import { useCallback, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, FileAudio, FileVideo, FileText, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type UiState = "idle" | "dragging" | "uploading" | "queued" | "error";

const AUDIO_EXT = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"];
const VIDEO_EXT = [".mp4", ".mov", ".mkv", ".avi", ".webm"];
const TEXT_EXT = [".txt", ".md", ".json"];
const ALL_EXT = [...AUDIO_EXT, ...VIDEO_EXT, ...TEXT_EXT];

function detectArtifactType(fileName: string): "audio" | "video" | "text" | null {
  const ext = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
  if (AUDIO_EXT.includes(ext)) return "audio";
  if (VIDEO_EXT.includes(ext)) return "video";
  if (TEXT_EXT.includes(ext)) return "text";
  return null;
}

function fileIcon(type: "audio" | "video" | "text" | null) {
  if (type === "audio") return FileAudio;
  if (type === "video") return FileVideo;
  return FileText;
}

export function UploadForm({ onQueued }: { onQueued?: (jobId: string) => void }) {
  const [state, setState] = useState<UiState>("idle");
  const [fileName, setFileName] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(async (file: File) => {
    const artifactType = detectArtifactType(file.name);
    if (!artifactType) {
      setState("error");
      setErrorMsg(`"${file.name.split(".").pop()}" isn't a supported file type.`);
      return;
    }

    setFileName(file.name);
    setState("uploading");
    setErrorMsg(null);

    try {
      // 1. Upload the raw file to Storage
      const storagePath = `${Date.now()}-${file.name}`;
      const { error: uploadError } = await supabase.storage
        .from("raw-uploads")
        .upload(storagePath, file, { upsert: false });

      if (uploadError) throw uploadError;

      // 2. Insert the jobs row — THIS is what fires the backend automatically
      const { data: job, error: insertError } = await supabase
        .from("jobs")
        .insert({
          file_name: file.name,
          file_path: storagePath,
          artifact_type: artifactType,
          status: "pending",
        })
        .select()
        .single();

      if (insertError) throw insertError;

      setState("queued");
      onQueued?.(job.id);
    } catch (err) {
      setState("error");
      setErrorMsg(err instanceof Error ? err.message : "Upload failed — try again.");
    }
  }, [onQueued]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setState("idle");
      const file = e.dataTransfer.files?.[0];
      if (file) uploadFile(file);
    },
    [uploadFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setState("dragging");
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setState((s) => (s === "dragging" ? "idle" : s));
  }, []);

  const handleFilePick = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) uploadFile(file);
    },
    [uploadFile]
  );

  const reset = () => {
    setState("idle");
    setFileName(null);
    setErrorMsg(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const Icon = fileIcon(fileName ? detectArtifactType(fileName) : null);

  return (
    <div className="w-full max-w-xl">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => state === "idle" && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && state === "idle") inputRef.current?.click();
        }}
        aria-label="Upload a call recording, video, or text export"
        className={cn(
          "relative flex min-h-[280px] w-full cursor-pointer flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed p-10 text-center transition-colors duration-200",
          state === "dragging" && "border-gold bg-gold/5",
          state === "idle" && "border-ink-border bg-ink-panel/60 hover:border-gold/50",
          (state === "uploading" || state === "queued") && "border-teal/50 bg-ink-panel/60 cursor-default",
          state === "error" && "border-brick/60 bg-brick/5 cursor-default"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ALL_EXT.join(",")}
          onChange={handleFilePick}
          className="sr-only"
          aria-hidden="true"
        />

        <AnimatePresence mode="wait">
          {state === "idle" || state === "dragging" ? (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4"
            >
              <UploadCloud className={cn("h-10 w-10 transition-colors", state === "dragging" ? "text-gold" : "text-cream-dim")} />
              <div>
                <p className="font-sans text-base text-cream">
                  Drop a call, video, or chat export here
                </p>
                <p className="mt-1 font-mono text-xs text-cream-dim">
                  or click to browse — mp3, wav, mp4, mov, txt, and more
                </p>
              </div>
            </motion.div>
          ) : state === "uploading" ? (
            <motion.div
              key="uploading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4"
            >
              <Loader2 className="h-10 w-10 animate-spin text-teal" />
              <p className="font-mono text-sm text-cream">Uploading {fileName}…</p>
            </motion.div>
          ) : state === "queued" ? (
            <motion.div
              key="queued"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center gap-4"
            >
              <CheckCircle2 className="h-10 w-10 text-teal" />
              <div>
                <div className="flex items-center justify-center gap-2 font-sans text-base text-cream">
                  <Icon className="h-4 w-4 text-cream-dim" />
                  {fileName}
                </div>
                <p className="mt-1 font-mono text-xs text-teal">queued — processing will start automatically</p>
              </div>
              <Button variant="outline" size="sm" onClick={reset}>
                Upload another
              </Button>
            </motion.div>
          ) : (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col items-center gap-4"
            >
              <XCircle className="h-10 w-10 text-brick" />
              <div>
                <p className="font-sans text-base text-cream">Couldn&apos;t queue that file</p>
                <p className="mt-1 font-mono text-xs text-brick">{errorMsg}</p>
              </div>
              <Button variant="outline" size="sm" onClick={reset}>
                Try again
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
