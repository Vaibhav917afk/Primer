import { createClient } from "@/lib/supabase/server";
import { getActiveOrgId } from "@/lib/get-active-org";
import { AddRepButton } from "@/components/team/add-rep-button";
import { Badge } from "@/components/ui/badge";

export default async function TeamPage() {
  const supabase = await createClient();
  const orgId = await getActiveOrgId();

  const { data: members } = await supabase
    .from("org_members")
    .select("id, role, full_name, user_id")
    .eq("org_id", orgId ?? "");

  const { data: pendingInvites } = await supabase
    .from("org_invites")
    .select("id, email, role")
    .eq("org_id", orgId ?? "");

  return (
    <div className="px-8 py-10">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl italic text-ink">Team</h1>
          <p className="mt-2 text-sm text-ink-dim">Reps in your organization, and anyone still pending an invite.</p>
        </div>
        {orgId && <AddRepButton orgId={orgId} />}
      </div>

      <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(members ?? []).map((m) => (
          <div key={m.id} className="rounded-lg border border-panel-border bg-panel p-4">
            <p className="font-medium text-ink">{m.full_name || "Unnamed rep"}</p>
            <Badge variant="gold" className="mt-2 capitalize">
              {m.role}
            </Badge>
          </div>
        ))}
      </div>

      {pendingInvites && pendingInvites.length > 0 && (
        <div className="mt-10">
          <p className="mb-3 text-sm font-medium text-ink-dim">Pending invites</p>
          <div className="flex flex-col gap-2">
            {pendingInvites.map((inv) => (
              <div
                key={inv.id}
                className="flex items-center justify-between rounded-md border border-dashed border-panel-border px-4 py-2.5 text-sm"
              >
                <span className="text-ink">{inv.email}</span>
                <Badge variant="neutral" className="capitalize">
                  {inv.role} · not yet signed in
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
