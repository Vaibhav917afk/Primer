import { createClient } from "@/lib/supabase/server";
import { getActiveOrgId } from "@/lib/get-active-org";
import { UploadForm } from "@/components/upload/upload-form";

export default async function UploadPage() {
  const supabase = await createClient();
  const orgId = await getActiveOrgId();

  const { data: prospects } = await supabase.from("prospects").select("*").eq("org_id", orgId ?? "").order("name");

  return (
    <div className="px-8 py-10">
      <h1 className="font-serif text-2xl italic text-ink">Ingest a Conversation</h1>
      <p className="mt-2 max-w-xl text-sm text-ink-dim">
        Every file runs through the full verified pipeline automatically — transcription, extraction, independent
        verification, and scoring. No manual step needed after this.
      </p>

      <div className="mt-8">{orgId && <UploadForm orgId={orgId} prospects={prospects ?? []} />}</div>
    </div>
  );
}
