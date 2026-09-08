import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getActiveOrgId } from "@/lib/get-active-org";
import { Badge, riskVariant } from "@/components/ui/badge";
import { computeScoreDeltas, type ScoreHistoryRow } from "@/lib/scoring";

function StatCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "teal" | "brick" }) {
  return (
    <div className="rounded-lg border border-panel-border bg-panel p-5">
      <p className="font-mono text-xs uppercase tracking-wide text-ink-faint">{label}</p>
      <p className={`mt-2 text-2xl font-medium ${tone === "teal" ? "text-teal" : tone === "brick" ? "text-brick" : "text-ink"}`}>
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-ink-dim">{sub}</p>}
    </div>
  );
}

export default async function DashboardPage() {
  const supabase = await createClient();
  const orgId = await getActiveOrgId();

  const { data: prospects } = await supabase.from("prospects").select("*").eq("org_id", orgId ?? "");
  const list = prospects ?? [];

  const prospectIds = list.map((p) => p.id);
  const { data: scoreHistory } =
    prospectIds.length > 0
      ? await supabase
          .from("score_history")
          .select("prospect_id, interest_score, risk_score, created_at")
          .in("prospect_id", prospectIds)
      : { data: [] };

  const deltas = computeScoreDeltas((scoreHistory as ScoreHistoryRow[]) ?? []);

  const activeCount = list.length;
  const totalPipeline = list.reduce((sum, p) => sum + (p.deal_value ?? 0), 0);
  const atRiskValue = list.filter((p) => p.risk_level === "high").reduce((sum, p) => sum + (p.deal_value ?? 0), 0);
  const risingCount = Array.from(deltas.values()).filter((d) => d.interestDelta > 0).length;

  const priority = [...list].sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0)).slice(0, 5);

  return (
    <div className="px-8 py-10">
      <h1 className="font-serif text-2xl italic text-ink">Executive Dashboard</h1>
      <p className="mt-2 text-sm text-ink-dim">A verified overview of every prospect in this organization.</p>

      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Active Prospects" value={String(activeCount)} />
        <StatCard label="Total Pipeline Value" value={`$${totalPipeline.toLocaleString()}`} />
        <StatCard label="Pipeline at Risk" value={`$${atRiskValue.toLocaleString()}`} tone="brick" />
        <StatCard label="Rising Interest" value={`${risingCount} prospect${risingCount === 1 ? "" : "s"}`} tone="teal" />
      </div>

      <div className="mt-10">
        <h2 className="text-sm font-medium text-ink">Priority &amp; Risk Radar</h2>
        <p className="text-xs text-ink-dim">Ranked by risk score — the ones worth checking on first.</p>

        {priority.length === 0 ? (
          <p className="mt-4 text-sm text-ink-dim">No prospects yet — add one from the Prospects page.</p>
        ) : (
          <div className="mt-4 flex flex-col gap-2">
            {priority.map((p) => (
              <Link
                key={p.id}
                href={`/prospects/${p.id}`}
                className="flex items-center justify-between gap-4 rounded-md border border-panel-border bg-panel px-4 py-3 hover:shadow-sm"
              >
                <div className="min-w-0">
                  <p className="truncate font-serif italic text-ink">{p.name ?? "Unnamed prospect"}</p>
                  <p className="truncate text-xs text-ink-dim">{p.company ?? "—"}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {p.deal_value !== null && <span className="font-mono text-xs text-ink-dim">${p.deal_value.toLocaleString()}</span>}
                  <Badge variant={riskVariant(p.risk_level)} className="capitalize">
                    {p.risk_level}
                  </Badge>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
