"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronsUpDown, Check } from "lucide-react";
import { switchOrg } from "@/app/actions/org";

export function OrgSwitcher({
  memberships,
  activeOrgId,
}: {
  memberships: { orgId: string; name: string }[];
  activeOrgId: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = memberships.find((m) => m.orgId === activeOrgId);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  if (memberships.length <= 1) {
    return <p className="truncate px-2 font-mono text-xs uppercase tracking-wide text-ink-faint">{active?.name}</p>;
  }

  return (
    <div ref={ref} className="relative px-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-md border border-panel-border bg-panel px-2.5 py-1.5 text-left text-sm text-ink"
      >
        <span className="truncate">{active?.name}</span>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
      </button>

      {open && (
        <div className="absolute left-2 right-2 top-full z-10 mt-1 overflow-hidden rounded-md border border-panel-border bg-panel shadow-md">
          {memberships.map((m) => (
            <form key={m.orgId} action={switchOrg.bind(null, m.orgId)}>
              <button
                type="submit"
                className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-ink hover:bg-paper"
              >
                <span className="truncate">{m.name}</span>
                {m.orgId === activeOrgId && <Check className="h-3.5 w-3.5 text-gold" />}
              </button>
            </form>
          ))}
        </div>
      )}
    </div>
  );
}
