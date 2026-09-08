"use client";

import { motion } from "framer-motion";
import { Mic, Video, FileText, TriangleAlert } from "lucide-react";

interface JobRow {
  id: string;
  file_name: string;
  artifact_type: string | null;
  status: string;
  created_at: string;
  transcript_json: {
    agreement_count?: number;
    disagreement_count?: number;
    gemini_only_count?: number;
    segments?: { speaker: string; text: string }[];
  } | null;
}

const ICONS: Record<string, typeof Mic> = { audio: Mic, video: Video, text: FileText };

export function ConversationTimeline({ jobs }: { jobs: JobRow[] }) {
  if (jobs.length === 0) {
    return <p className="text-sm text-ink-dim">No calls on file yet for this prospect.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {jobs.map((job, i) => {
        const Icon = ICONS[job.artifact_type ?? "text"] ?? FileText;
        const tj = job.transcript_json;
        const scrutinyCount = (tj?.disagreement_count ?? 0) + (tj?.gemini_only_count ?? 0);
        const excerpt = tj?.segments?.slice(0, 2).map((s) => s.text).join(" ") ?? "";

        return (
          <motion.div
            key={job.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i * 0.03, 0.2) }}
            className="rounded-md border border-panel-border bg-panel p-4"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-ink-faint" />
                <span className="text-sm font-medium text-ink">{job.file_name}</span>
              </div>
              <span className="font-mono text-xs text-ink-faint">
                {new Date(job.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
              </span>
            </div>

            {excerpt && <p className="mt-2 line-clamp-2 text-sm text-ink-dim">{excerpt}</p>}

            <div className="mt-2 flex items-center gap-3 text-xs">
              <span className="text-ink-faint capitalize">{job.status}</span>
              {scrutinyCount > 0 && (
                <span
                  className="flex items-center gap-1 text-gold"
                  title="Segments where the two independent transcription systems disagreed, or one caught something the other missed entirely — flagged for a human glance, not silently trusted."
                >
                  <TriangleAlert className="h-3 w-3" /> {scrutinyCount} segment{scrutinyCount === 1 ? "" : "s"} needed extra scrutiny
                </span>
              )}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
