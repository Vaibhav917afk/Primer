"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import type { TrendPoint, TopObjection } from "@/lib/analytics";

const RISK_COLORS: Record<string, string> = { low: "#2F6B62", medium: "#A6742C", high: "#A23B28", unknown: "#8B99A8" };

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-panel-border bg-panel p-5">
      <p className="text-sm font-medium text-ink">{title}</p>
      {subtitle && <p className="text-xs text-ink-dim">{subtitle}</p>}
      <div className="mt-4 h-64">{children}</div>
    </div>
  );
}

export function AnalyticsCharts({
  trend,
  riskBreakdown,
  stageBreakdown,
  topObjections,
}: {
  trend: TrendPoint[];
  riskBreakdown: { level: string; count: number }[];
  stageBreakdown: { stage: string; count: number }[];
  topObjections: TopObjection[];
}) {
  return (
    <div className="mt-8 grid grid-cols-1 gap-5 lg:grid-cols-2">
      <ChartCard title="Average Score Trajectory" subtitle="Interest and risk, aligned by each prospect's own call sequence">
        {trend.length === 0 ? (
          <EmptyState text="Not enough call history yet — needs at least 2 calls with a prospect." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trend}>
              <CartesianGrid stroke="#E4E1D9" vertical={false} />
              <XAxis dataKey="callIndex" tickFormatter={(v) => `Call ${v}`} fontSize={11} stroke="#8B99A8" />
              <YAxis domain={[0, 100]} fontSize={11} stroke="#8B99A8" />
              <Tooltip labelFormatter={(v) => `Call ${v}`} />
              <Line type="monotone" dataKey="avgInterest" name="Interest" stroke="#2F6B62" strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="avgRisk" name="Risk" stroke="#A23B28" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="Active Prospects by Stage">
        {stageBreakdown.length === 0 ? (
          <EmptyState text="No prospects yet." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={stageBreakdown}>
              <CartesianGrid stroke="#E4E1D9" vertical={false} />
              <XAxis dataKey="stage" fontSize={11} stroke="#8B99A8" className="capitalize" />
              <YAxis fontSize={11} stroke="#8B99A8" allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#A6742C" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="Risk Level Breakdown">
        {riskBreakdown.length === 0 ? (
          <EmptyState text="No prospects yet." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={riskBreakdown} dataKey="count" nameKey="level" innerRadius={55} outerRadius={85} paddingAngle={2}>
                {riskBreakdown.map((entry) => (
                  <Cell key={entry.level} fill={RISK_COLORS[entry.level]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        )}
        <div className="mt-2 flex flex-wrap gap-3">
          {riskBreakdown.map((r) => (
            <span key={r.level} className="flex items-center gap-1.5 text-xs text-ink-dim">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: RISK_COLORS[r.level] }} />
              {r.level} risk: {r.count}
            </span>
          ))}
        </div>
      </ChartCard>

      <ChartCard title="Top Unresolved Objections" subtitle="Across every prospect in the org">
        {topObjections.length === 0 ? (
          <EmptyState text="No open objections on file." />
        ) : (
          <div className="flex flex-col gap-2.5 overflow-y-auto">
            {topObjections.slice(0, 6).map((o, i) => (
              <div key={i} className="flex items-start justify-between gap-3 border-b border-panel-border pb-2 last:border-0">
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">{o.text}</p>
                  <p className="truncate text-xs text-ink-dim">{o.prospectNames.join(", ")}</p>
                </div>
                <Badge variant={o.count > 1 ? "brick" : "neutral"} className="shrink-0">
                  {o.count} prospect{o.count === 1 ? "" : "s"}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </ChartCard>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center text-center text-sm text-ink-dim">{text}</div>;
}
