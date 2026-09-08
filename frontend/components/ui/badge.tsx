import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      neutral: "bg-paper text-ink-dim border border-panel-border",
      gold: "bg-gold-soft text-gold",
      teal: "bg-teal-soft text-teal",
      brick: "bg-brick-soft text-brick",
    },
  },
  defaultVariants: { variant: "neutral" },
});

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export function riskVariant(riskLevel: string | null | undefined): "teal" | "gold" | "brick" | "neutral" {
  if (riskLevel === "low") return "teal";
  if (riskLevel === "medium") return "gold";
  if (riskLevel === "high") return "brick";
  return "neutral";
}
