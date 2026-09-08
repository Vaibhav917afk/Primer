"use client";

import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowUp, ArrowDown, ShieldCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { Badge, riskVariant } from "@/components/ui/badge";
import { createClient } from "@/lib/supabase/client";
import { computeScoreDeltas, type ScoreHistoryRow } from "@/lib/scoring";
import { FIELD_ORDER, FIELD_LABELS, STAGE_OPTIONS, type Claim, type Prospect, type Recommendation } from "@/lib/types";
import { UploadForm } from "@/components/upload/upload-form";
import { ConversationTimeline } from "@/components/prospects/conversation-timeline";
import { BeliefState } from "@/components/belief-state/belief-state";
import type { JobEntity } from "@/lib/entities";

type Tab = "brief" | "ingestion" | "belief";

export function ProspectDetail({
  prospect,
  openClaims,
  resolvedClaims,
  recommendation,
  scoreHistory,
  jobs,
  competitorMentions,
}: {
  prospect: Prospect;
  openClaims: Claim[];
  resolvedClaims: Claim[];
  recommendation: Recommendation | null;
  scoreHistory: ScoreHistoryRow[];
  jobs: {
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
  }[];
  competitorMentions: JobEntity[];
}) {
  const [tab, setTab] = useState<Tab>("brief");
  const [stage, setStage] = useState(prospect.stage);
  const [savingStage, setSavingStage] = useState(false);
  const supabase = createClient();

  const delta = useMemo(() => computeScoreDeltas(scoreHistory).get(prospect.id), [scoreHistory, prospect.id]);

  const byField = useMemo(() => {
    const map = new Map<Claim["field"], Claim[]>();
    for (const c of openClaims) {
      const list = map.get(c.field) ?? [];
      list.push(c);
      map.set(c.field, list);
    }
    return map;
  }, [openClaims]);

  const confidence = useMemo(() => {
    if (openClaims.length === 0) return null;
    const confirmed = openClaims.filter((c) => c.status === "confirmed").length;
    return Math.round((confirmed / openClaims.length) * 100);
  }, [openClaims]);

  async function handleStageChange(newStage: string) {
    setStage(newStage);
    setSavingStage(true);
    await supabase.from("prospects").update({ stage: newStage }).eq("id", prospect.id);
    setSavingStage(false);
  }

  return (
    <div className="px-8 py-8">
      <Link href="/prospects" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-dim hover:text-ink">
        <ArrowLeft className="h-3.5 w-3.5" /> Prospects
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl italic text-ink">{prospect.name ?? "Unnamed prospect"}</h1>
          <p className="mt-1 text-sm text-ink-dim">
            {prospect.role_title ?? "—"} {prospect.company && <>&middot; {prospect.company}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={stage}
            onChange={(e) => handleStageChange(e.target.value)}
            disabled={savingStage}
            className="h-9 rounded-md border border-panel-border bg-panel px-2.5 text-sm capitalize text-ink"
          >
            {STAGE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <Badge variant={riskVariant(prospect.risk_level)} className="h-9 items-center capitalize">
            {prospect.risk_level} risk
          </Badge>
        </div>
      </div>

      <div className="mt-6 flex gap-1 border-b border-panel-border">
        {(
          [
            ["brief", "Brief"],
            ["ingestion", "Ingestion"],
            ["belief", "Belief State"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`relative px-4 py-2.5 text-sm transition-colors ${
              tab === key ? "text-ink" : "text-ink-dim hover:text-ink"
            }`}
          >
            {label}
            {tab === key && (
              <motion.div layoutId="tab-underline" className="absolute bottom-0 left-0 right-0 h-0.5 bg-gold" />
            )}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {tab === "brief" && (
          <motion.div
            key="brief"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="max-w-3xl py-8"
          >
            {prospect.persona_overview && <p className="text-ink">{prospect.persona_overview}</p>}

            {prospect.interest_score !== null && prospect.risk_score !== null && (
              <div className="mt-5 rounded-lg border border-panel-border bg-panel p-5">
                <div className="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-sm">
                  <span>
                    Interest <b className="text-teal">{prospect.interest_score}</b>/100
                    {delta && delta.interestDelta !== 0 && (
                      <span className={delta.interestDelta > 0 ? "text-teal" : "text-brick"}>
                        {" "}
                        ({delta.interestDelta > 0 ? "+" : ""}
                        {delta.interestDelta} since last call)
                      </span>
                    )}
                  </span>
                  <span>
                    Risk <b className="text-brick">{prospect.risk_score}</b>/100 · {prospect.risk_level}
                    {delta && delta.riskDelta !== 0 && (
                      <span className={delta.riskDelta < 0 ? "text-teal" : "text-brick"}>
                        {" "}
                        ({delta.riskDelta > 0 ? "+" : ""}
                        {delta.riskDelta} since last call)
                      </span>
                    )}
                  </span>
                  {confidence !== null && (
                    <span className="ml-auto flex items-center gap-1 text-ink-dim">
                      <ShieldCheck className="h-3.5 w-3.5" /> {confidence}% verified
                    </span>
                  )}
                </div>
                {prospect.score_summary && (
                  <p className="mt-3 text-sm text-ink-dim">
                    {prospect.score_summary}
                    {prospect.score_status === "partial" && (
                      <span title="This explanation couldn't be fully confirmed against the evidence — the numbers above are unaffected, this is only about the wording.">
                        {" "}
                        <TriangleAlert className="inline h-3.5 w-3.5 text-gold" />
                      </span>
                    )}
                  </p>
                )}
              </div>
            )}

            {recommendation && (
              <div className="mt-5 rounded-lg border border-gold/30 bg-gold-soft/40 p-5">
                <p className="font-mono text-xs uppercase tracking-wide text-gold">Next Call</p>
                {recommendation.recommended_opening && (
                  <p className="mt-2 text-sm text-ink">
                    <b>Open with:</b> {recommendation.recommended_opening}
                  </p>
                )}
                {recommendation.next_best_action && (
                  <p className="mt-1.5 text-sm text-ink">
                    <b>Do next:</b> {recommendation.next_best_action}
                  </p>
                )}
                {recommendation.talking_points && recommendation.talking_points.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-ink-dim">Talking points</p>
                    <ul className="mt-1 list-inside list-disc text-sm text-ink">
                      {recommendation.talking_points.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {recommendation.avoid && recommendation.avoid.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-brick">Avoid</p>
                    <ul className="mt-1 list-inside list-disc text-sm text-ink">
                      {recommendation.avoid.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {resolvedClaims.length > 0 && (
              <div className="mt-5 rounded-md border border-teal/30 bg-teal-soft/40 p-4">
                <p className="font-mono text-xs uppercase tracking-wide text-teal">Recently Resolved</p>
                <ul className="mt-2 flex flex-col gap-1.5 text-sm text-ink">
                  {resolvedClaims.slice(0, 2).map((c) => (
                    <li key={c.id}>{c.text}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-8 flex flex-col gap-6">
              {FIELD_ORDER.map((field) => {
                const claims = byField.get(field);
                if (!claims || claims.length === 0) return null;
                return (
                  <div key={field}>
                    <p className="mb-2 text-sm font-medium text-ink">{FIELD_LABELS[field]}</p>
                    <ul className="flex flex-col gap-2">
                      {claims.map((c) => (
                        <li key={c.id} className="rounded-md border border-panel-border bg-panel px-3.5 py-2.5 text-sm">
                          <span className="text-ink">{c.text}</span>
                          {c.evidence_line && (
                            <span className="font-mono text-ink-dim"> — &ldquo;{c.evidence_line}&rdquo;</span>
                          )}
                          {c.mention_count > 1 && (
                            <span className="ml-1 text-ink-faint">(mentioned {c.mention_count}x)</span>
                          )}
                          {c.status === "partial" && (
                            <span
                              className="ml-1 cursor-help text-gold"
                              title={c.verification_note ?? "Confirmed, but with lower confidence."}
                            >
                              ❗
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
              {openClaims.length === 0 && (
                <p className="text-sm text-ink-dim">No open items on file — nothing currently outstanding.</p>
              )}
            </div>
          </motion.div>
        )}

        {tab === "ingestion" && (
          <motion.div key="ingestion" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="max-w-2xl py-8">
            <UploadForm orgId={prospect.org_id} prospects={[prospect]} fixedProspect={prospect} />
            <div className="mt-10">
              <p className="mb-3 text-sm font-medium text-ink">Conversation History</p>
              <ConversationTimeline jobs={jobs} />
            </div>
          </motion.div>
        )}

        {tab === "belief" && (
          <motion.div key="belief" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="py-8">
            <BeliefState allClaims={[...openClaims, ...resolvedClaims]} competitorMentions={competitorMentions} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
