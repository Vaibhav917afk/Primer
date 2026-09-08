"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function OnboardingPage() {
  const router = useRouter();
  const supabase = createClient();
  const [orgName, setOrgName] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      setError("Session expired — please sign in again.");
      setLoading(false);
      return;
    }

    // One atomic call: creates the org AND adds this user as its first
    // admin in a single transaction — see create_organization() in the
    // migration. Two separate inserts from the browser hit a real
    // chicken-and-egg RLS problem (the organizations SELECT policy checks
    // org_members, but you aren't a member yet at the moment the org is
    // created), proven by direct debugging, not theory.
    const { data: newOrgId, error: rpcError } = await supabase.rpc("create_organization", {
      org_name: orgName,
      member_full_name: fullName || null,
    });

    if (rpcError || !newOrgId) {
      setError(rpcError?.message ?? "Couldn't create the organization.");
      setLoading(false);
      return;
    }

    router.push("/dashboard");
    router.refresh();
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-paper px-6">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="w-full max-w-sm"
      >
        <h1 className="font-serif text-3xl italic text-ink">Set up your organization</h1>
        <p className="mt-2 text-sm text-ink-dim">You&apos;ll be its first admin — you can add reps afterward.</p>

        <form onSubmit={handleSubmit} className="mt-8 flex flex-col gap-4">
          <div>
            <label htmlFor="orgName" className="mb-1.5 block text-sm text-ink">
              Organization name
            </label>
            <Input id="orgName" required value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Acme Global Enterprise" />
          </div>
          <div>
            <label htmlFor="fullName" className="mb-1.5 block text-sm text-ink">
              Your name
            </label>
            <Input id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Optional, for now" />
          </div>

          {error && <p className="text-sm text-brick">{error}</p>}

          <Button type="submit" variant="gold" disabled={loading} className="mt-2">
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Creating…
              </>
            ) : (
              "Create organization"
            )}
          </Button>
        </form>
      </motion.div>
    </main>
  );
}
