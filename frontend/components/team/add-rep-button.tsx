"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Plus, X, Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function AddRepButton({ orgId }: { orgId: string }) {
  const router = useRouter();
  const supabase = createClient();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("rep");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const { error } = await supabase.from("org_invites").insert({ org_id: orgId, email, role });

    if (error) {
      setError(error.message);
      setLoading(false);
      return;
    }

    setOpen(false);
    setEmail("");
    setLoading(false);
    router.refresh();
  }

  return (
    <>
      <Button variant="gold" size="sm" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" /> Add Rep
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
                <h2 className="font-serif text-lg italic text-ink">Add a rep</h2>
                <button onClick={() => setOpen(false)} className="text-ink-faint hover:text-ink">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <p className="mt-1.5 text-xs text-ink-dim">
                They get access automatically the moment they sign in with this email — whether they already have an
                account or sign up fresh.
              </p>

              <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
                <Input
                  type="email"
                  placeholder="their.email@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="h-10 rounded-md border border-panel-border bg-panel px-3 text-sm text-ink"
                >
                  <option value="rep">Rep</option>
                  <option value="admin">Admin</option>
                </select>

                {error && <p className="text-sm text-brick">{error}</p>}

                <Button type="submit" variant="gold" disabled={loading} className="mt-1">
                  {loading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Sending…
                    </>
                  ) : (
                    "Send invite"
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
