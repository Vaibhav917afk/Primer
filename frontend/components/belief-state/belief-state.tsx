"use client";

import { useState } from "react";
import { Check, Circle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Badge } from "@/components/ui/badge";
import type { JobEntity } from "@/lib/entities";
import type { Claim } from "@/lib/types";

export function BeliefState({
  allClaims,
  competitorMentions,
}: {
  allClaims: Claim[]; // open + resolved, so the Objections Log can show both states
  competitorMentions: JobEntity[];
}) {
  const supabase = createClient();
  const [fulfilledOverride, setFulfilledOverride] = useState<Record<string, boolean>>({});

  const objections = allClaims.filter((c) => c.field === "objection" && (c.state === "open" || c.state === "resolved"));
  const commitments = allClaims.filter((c) => c.field === "commitment" && c.state === "open");

  async function toggleFulfilled(claim: Claim) {
    const next = !(fulfilledOverride[claim.id] ?? claim.fulfilled);
    setFulfilledOverride((prev) => ({ ...prev, [claim.id]: next }));
    await supabase.from("claims").update({ fulfilled: next }).eq("id", claim.id);
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div>
        <p className="mb-2 text-sm font-medium text-ink">
          Objections Log <span className="text-ink-faint">({objections.filter((o) => o.state === "open").length} unresolved)</span>
        </p>
        <div className="flex flex-col gap-2">
          {objections.length === 0 && <p className="text-sm text-ink-dim">None on file.</p>}
          {objections.map((o) => (
            <div key={o.id} className="rounded-md border border-panel-border bg-panel p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-ink">{o.text}</p>
                <Badge variant={o.state === "resolved" ? "teal" : "brick"} className="shrink-0">
                  {o.state === "resolved" ? "Resolved" : "Open"}
                </Badge>
              </div>
              {o.evidence_line && <p className="mt-1 font-mono text-xs text-ink-dim">&ldquo;{o.evidence_line}&rdquo;</p>}
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-ink">Pending Commitments</p>
        <div className="flex flex-col gap-2">
          {commitments.length === 0 && <p className="text-sm text-ink-dim">None on file.</p>}
          {commitments.map((c) => {
            const fulfilled = fulfilledOverride[c.id] ?? c.fulfilled;
            return (
              <button
                key={c.id}
                onClick={() => toggleFulfilled(c)}
                className="flex w-full items-start gap-2.5 rounded-md border border-panel-border bg-panel p-3 text-left"
              >
                {fulfilled ? (
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-teal" />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                )}
                <div>
                  <p className={`text-sm ${fulfilled ? "text-ink-dim line-through" : "text-ink"}`}>{c.text}</p>
                  {c.evidence_line && <p className="mt-0.5 font-mono text-xs text-ink-faint">&ldquo;{c.evidence_line}&rdquo;</p>}
                </div>
              </button>
            );
          })}
        </div>

        <p className="mb-2 mt-6 text-sm font-medium text-ink">Competitor / Other Mentions</p>
        {competitorMentions.length === 0 ? (
          <p className="text-sm text-ink-dim">No competitor references found in transcripts — section omitted, not guessed.</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {competitorMentions.map((e, i) => (
              <Badge key={i} variant="neutral">
                {e.text}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
