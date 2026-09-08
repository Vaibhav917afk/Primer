import { createClient } from "@/lib/supabase/server";
import { getActiveOrgId } from "@/lib/get-active-org";
import { computeOrgTrend, computeRiskBreakdown, computeStageBreakdown, computeTopObjections } from "@/lib/analytics";
import type { ScoreHistoryRow } from "@/lib/scoring";
import type { Claim } from "@/lib/types";
import { AnalyticsCharts } from "@/components/analytics/analytics-charts";

export default async function AnalyticsPage() {
  const supabase = await createClient();
  const orgId = await getActiveOrgId();

  const { data: prospects } = await supabase.from("prospects").select("*").eq("org_id", orgId ?? "");
  const list = prospects ?? [];
  const prospectIds = list.length > 0 ? list.map((p) => p.id) : ["__none__"];
  const prospectNameById = new Map(list.map((p) => [p.id, p.name ?? "Unnamed"]));

  const { data: scoreHistory } = await supabase
    .from("score_history")
    .select("prospect_id, interest_score, risk_score, created_at")
    .in("prospect_id", prospectIds);

  const { data: claims } = await supabase.from("claims").select("*").in("prospect_id", prospectIds);

  const trend = computeOrgTrend((scoreHistory as ScoreHistoryRow[]) ?? []);
  const riskBreakdown = computeRiskBreakdown(list);
  const stageBreakdown = computeStageBreakdown(list);
  const topObjections = computeTopObjections((claims as Claim[]) ?? [], prospectNameById);

  return (
    <div className="px-8 py-10">
      <h1 className="font-serif text-2xl italic text-ink">Deal Health Analytics</h1>
      <p className="mt-2 text-sm text-ink-dim">Aggregated across every prospect in this organization.</p>

      <AnalyticsCharts trend={trend} riskBreakdown={riskBreakdown} stageBreakdown={stageBreakdown} topObjections={topObjections} />
    </div>
  );
}
