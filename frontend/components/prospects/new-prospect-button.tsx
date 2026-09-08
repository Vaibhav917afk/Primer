"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Plus, X, Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function NewProspectButton({ orgId }: { orgId: string }) {
  const router = useRouter();
  const supabase = createClient();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", company: "", role_title: "", email: "" });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const { data, error } = await supabase
      .from("prospects")
      .insert({
        org_id: orgId,
        name: form.name || null,
        company: form.company || null,
        role_title: form.role_title || null,
        email: form.email || null,
        stage: "lead",
        risk_level: "unknown",
      })
      .select()
      .single();

    if (error || !data) {
      setError(error?.message ?? "Couldn't create the prospect.");
      setLoading(false);
      return;
    }

    router.push(`/prospects/${data.id}`);
    router.refresh();
  }

  return (
    <>
      <Button variant="gold" size="sm" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" /> New Prospect
      </Button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4"
            onClick={() => setOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.97, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.15 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-sm rounded-lg border border-panel-border bg-panel p-6"
            >
              <div className="flex items-center justify-between">
                <h2 className="font-serif text-lg italic text-ink">New prospect</h2>
                <button onClick={() => setOpen(false)} className="text-ink-faint hover:text-ink">
                  <X className="h-4 w-4" />
                </button>
              </div>

              <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
                <Input
                  placeholder="Name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
                <Input
                  placeholder="Company"
                  value={form.company}
                  onChange={(e) => setForm({ ...form, company: e.target.value })}
                />
                <Input
                  placeholder="Role / title"
                  value={form.role_title}
                  onChange={(e) => setForm({ ...form, role_title: e.target.value })}
                />
                <Input
                  type="email"
                  placeholder="Email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />

                {error && <p className="text-sm text-brick">{error}</p>}

                <Button type="submit" variant="gold" disabled={loading} className="mt-1">
                  {loading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Creating…
                    </>
                  ) : (
                    "Create"
                  )}
                </Button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
