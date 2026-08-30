"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Clock, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { supabase, type Job } from "@/lib/supabase";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<Job["status"], { icon: typeof Clock; label: string; className: string }> = {
  pending: { icon: Clock, label: "queued", className: "text-cream-dim" },
  processing: { icon: Loader2, label: "processing", className: "text-teal" },
  done: { icon: CheckCircle2, label: "done", className: "text-teal" },
  failed: { icon: XCircle, label: "failed", className: "text-brick" },
};

export function JobList() {
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    let mounted = true;

    supabase
      .from("jobs")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(10)
      .then(({ data }) => {
        if (mounted && data) setJobs(data as Job[]);
      });

    // Live updates — this is what makes "processing" flip to "done" on
    // screen without a page refresh, proving the automatic pipeline to
    // whoever's watching.
    const channel = supabase
      .channel("jobs-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "jobs" },
        (payload) => {
          setJobs((prev) => {
            if (payload.eventType === "INSERT") {
              const next = payload.new as Job;
              if (prev.some((j) => j.id === next.id)) return prev;
              return [next, ...prev].slice(0, 10);
            }
            if (payload.eventType === "UPDATE") {
              const next = payload.new as Job;
              return prev.map((j) => (j.id === next.id ? next : j));
            }
            return prev;
          });
        }
      )
      .subscribe();

    return () => {
      mounted = false;
      supabase.removeChannel(channel);
    };
  }, []);

  if (jobs.length === 0) return null;

  return (
    <div className="mt-10 w-full max-w-xl">
      <p className="mb-3 font-mono text-xs uppercase tracking-wider text-cream-dim">recent</p>
      <ul className="flex flex-col gap-2">
        <AnimatePresence initial={false}>
          {jobs.map((job) => {
            const cfg = STATUS_CONFIG[job.status];
            const StatusIcon = cfg.icon;
            return (
              <motion.li
                key={job.id}
                layout
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="flex items-center justify-between gap-3 rounded-md border border-ink-border bg-ink-panel/60 px-4 py-3"
              >
                <span className="truncate font-sans text-sm text-cream">{job.file_name}</span>
                <span className={cn("flex shrink-0 items-center gap-1.5 font-mono text-xs", cfg.className)}>
                  <StatusIcon className={cn("h-3.5 w-3.5", job.status === "processing" && "animate-spin")} />
                  {cfg.label}
                </span>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </div>
  );
}
