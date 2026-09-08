"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowUp, ArrowDown, Search } from "lucide-react";
import { Badge, riskVariant } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { computeScoreDeltas, type ScoreHistoryRow } from "@/lib/scoring";
import type { Prospect } from "@/lib/types";
import { STAGE_OPTIONS } from "@/lib/types";

export function ProspectGrid({ prospects, scoreHistory }: { prospects: Prospect[]; scoreHistory: ScoreHistoryRow[] }) {
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState<string>("all");
  const [riskFilter, setRiskFilter] = useState<string>("all");

  const deltas = useMemo(() => computeScoreDeltas(scoreHistory), [scoreHistory]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return prospects.filter((p) => {
      if (stageFilter !== "all" && p.stage !== stageFilter) return false;
      if (riskFilter !== "all" && p.risk_level !== riskFilter) return false;
      if (q) {
        const haystack = `${p.name ?? ""} ${p.company ?? ""} ${p.role_title ?? ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [prospects, stageFilter, riskFilter, search]);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
          <Input
            placeholder="Search prospects, companies…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
          />
        </div>
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
          className="h-10 rounded-md border border-panel-border bg-panel px-3 text-sm text-ink"
        >
          <option value="all">All stages</option>
          {STAGE_OPTIONS.map((s) => (
            <option key={s} value={s} className="capitalize">
              {s}
            </option>
          ))}
        </select>
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          className="h-10 rounded-md border border-panel-border bg-panel px-3 text-sm text-ink"
        >
          <option value="all">All risk levels</option>
          <option value="low">Low risk</option>
          <option value="medium">Medium risk</option>
          <option value="high">High risk</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-ink-dim">No prospects match those filters.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((p, i) => {
            const delta = deltas.get(p.id);
            return (
              <motion.div
                key={p.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: Math.min(i * 0.04, 0.3), ease: "easeOut" }}
              >
                <Link
                  href={`/prospects/${p.id}`}
                  className="block h-full rounded-lg border border-panel-border bg-panel p-5 transition-shadow hover:shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-serif text-lg italic text-ink">{p.name ?? "Unnamed prospect"}</p>
                      <p className="truncate text-sm text-ink-dim">{p.company ?? "—"}</p>
                    </div>
                    <Badge variant={riskVariant(p.risk_level)} className="shrink-0 capitalize">
                      {p.risk_level ?? "unknown"}
                    </Badge>
                  </div>

                  {p.role_title && <p className="mt-1 text-xs text-ink-faint">{p.role_title}</p>}

                  {p.persona_overview && <p className="mt-3 line-clamp-2 text-sm text-ink-dim">{p.persona_overview}</p>}

                  <div className="mt-4 flex items-center justify-between border-t border-panel-border pt-3">
                    <Badge variant="neutral" className="capitalize">
                      {p.stage}
                    </Badge>
                    <div className="flex items-center gap-3 font-mono text-xs">
                      {p.interest_score !== null && (
                        <span className="flex items-center gap-0.5 text-teal">
                          {p.interest_score}
                          {delta && delta.interestDelta !== 0 && (
                            <>
                              {delta.interestDelta > 0 ? (
                                <ArrowUp className="h-3 w-3" />
                              ) : (
                                <ArrowDown className="h-3 w-3" />
                              )}
                            </>
                          )}
                        </span>
                      )}
                      {p.deal_value !== null && (
                        <span className="text-ink-dim">${p.deal_value.toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                </Link>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
