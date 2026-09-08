import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { SidebarNav } from "@/components/shell/sidebar-nav";
import { OrgSwitcher } from "@/components/shell/org-switcher";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  let { data: memberships } = await supabase
    .from("org_members")
    .select("org_id, role, organizations(id, name)")
    .eq("user_id", user.id);

  // Someone who already had an account BEFORE being invited won't get the
  // signup trigger — claim any pending invite for their email right here,
  // the moment they load an authenticated page with no org yet.
  if (!memberships || memberships.length === 0) {
    const { data: invites } = await supabase.from("org_invites").select("*").eq("email", user.email ?? "");

    if (invites && invites.length > 0) {
      for (const invite of invites) {
        await supabase.from("org_members").insert({ org_id: invite.org_id, user_id: user.id, role: invite.role });
      }
      await supabase.from("org_invites").delete().eq("email", user.email ?? "");

      const refetched = await supabase
        .from("org_members")
        .select("org_id, role, organizations(id, name)")
        .eq("user_id", user.id);
      memberships = refetched.data;
    }
  }

  if (!memberships || memberships.length === 0) redirect("/onboarding");

  const cookieStore = await cookies();
  const activeOrgId = cookieStore.get("primer_active_org")?.value;
  const active = memberships.find((m) => m.org_id === activeOrgId) ?? memberships[0];
  const org = active.organizations as unknown as { id: string; name: string };

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="flex w-60 shrink-0 flex-col border-r border-panel-border bg-panel px-4 py-6">
        <div className="mb-6 px-2">
          <p className="font-serif text-xl italic text-ink">Primer</p>
        </div>

        <OrgSwitcher
          memberships={memberships.map((m) => ({
            orgId: m.org_id,
            name: (m.organizations as unknown as { name: string }).name,
          }))}
          activeOrgId={org.id}
        />

        <div className="mt-6">
          <SidebarNav />
        </div>

        <div className="mt-auto px-2 pt-6">
          <p className="truncate text-xs text-ink-dim">{user.email}</p>
          <p className="text-xs capitalize text-ink-faint">{active.role}</p>
        </div>
      </aside>

      <main className="flex-1 overflow-x-hidden">{children}</main>
    </div>
  );
}
