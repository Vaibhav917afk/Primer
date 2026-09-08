import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ProspectDetail } from "@/components/prospects/prospect-detail";
import { extractCompetitorMentions } from "@/lib/entities";
import type { ScoreHistoryRow } from "@/lib/scoring";

export default async function ProspectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();

  const { data: prospect } = await supabase.from("prospects").select("*").eq("id", id).maybeSingle();
  if (!prospect) notFound();

  const { data: openClaims } = await supabase
    .from("claims")
    .select("*")
    .eq("prospect_id", id)
    .eq("state", "open")
    .order("field");

  const { data: resolvedClaims } = await supabase
    .from("claims")
    .select("*")
    .eq("prospect_id", id)
    .eq("state", "resolved")
    .order("created_at", { ascending: false });

  const { data: recommendation } = await supabase
    .from("recommendations")
    .select("*")
    .eq("prospect_id", id)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const { data: scoreHistory } = await supabase
    .from("score_history")
    .select("prospect_id, interest_score, risk_score, created_at")
    .eq("prospect_id", id);

  const { data: jobs } = await supabase
    .from("jobs")
    .select("id, file_name, artifact_type, status, created_at, transcript_json")
    .eq("prospect_id", id)
    .order("created_at", { ascending: false });

  const competitorMentions = extractCompetitorMentions(jobs ?? [], prospect.company);

  return (
    <ProspectDetail
      prospect={prospect}
      openClaims={openClaims ?? []}
      resolvedClaims={resolvedClaims ?? []}
      recommendation={recommendation}
      scoreHistory={(scoreHistory as ScoreHistoryRow[]) ?? []}
      jobs={jobs ?? []}
      competitorMentions={competitorMentions}
    />
  );
}
