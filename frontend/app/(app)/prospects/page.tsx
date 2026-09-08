import { createClient } from "@/lib/supabase/server";
import { getActiveOrgId } from "@/lib/get-active-org";
import { ProspectGrid } from "@/components/prospects/prospect-grid";
import { NewProspectButton } from "@/components/prospects/new-prospect-button";
import type { ScoreHistoryRow } from "@/lib/scoring";

export default async function ProspectsPage() {
  const supabase = await createClient();
  const orgId = await getActiveOrgId();

  const { data: prospects, error } = await supabase
    .from("prospects")
    .select("*")
    .eq("org_id", orgId ?? "")
    .order("risk_score", { ascending: false, nullsFirst: false });

  const prospectIds = (prospects ?? []).map((p) => p.id);
  const { data: scoreHistory } =
    prospectIds.length > 0
      ? await supabase.from("score_history").select("prospect_id, interest_score, risk_score, created_at").in("prospect_id", prospectIds)
      : { data: [] };

  return (
    <div className="px-8 py-10">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl italic text-ink">Prospects</h1>
          <p className="mt-2 text-sm text-ink-dim">Every conversation partner your organization has on file.</p>
        </div>
        {orgId && <NewProspectButton orgId={orgId} />}
      </div>

      {error && <p className="mt-6 text-sm text-brick">Couldn&apos;t load prospects: {error.message}</p>}

      <div className="mt-8">
        <ProspectGrid prospects={prospects ?? []} scoreHistory={(scoreHistory as ScoreHistoryRow[]) ?? []} />
      </div>
    </div>
  );
}
