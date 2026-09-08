"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGrid, Users, Upload, BarChart3, UserCog } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/prospects", label: "Prospects", icon: Users },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/team", label: "Team", icon: UserCog },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-0.5">
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
              active ? "bg-gold-soft text-ink font-medium" : "text-ink-dim hover:bg-paper hover:text-ink"
            )}
          >
            <Icon className="h-4 w-4" strokeWidth={1.75} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
