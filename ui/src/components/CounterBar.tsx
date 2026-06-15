import type { Cost } from "../types";
import { humantok, money, pct } from "../lib/format";
import { CostSparkline } from "./CostSparkline";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bento flex flex-col gap-1 p-4">
      <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
      <span className="num text-xl text-fg">{value}</span>
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}

export function CounterBar({ cost, series }: { cost: Cost | null; series: number[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Input tokens" value={cost ? humantok(cost.input_tokens) : "0"} />
      <Stat label="Output tokens" value={cost ? humantok(cost.output_tokens) : "0"} />
      <Stat
        label="Cost"
        value={cost ? (cost.pricing_known ? money(cost.cost_usd) : "—") : "—"}
        hint={cost && !cost.pricing_known ? "pricing unknown for model" : undefined}
      />
      <Stat
        label="Cache hit"
        value={cost ? pct(cost.cache_hit_ratio) : "0%"}
        hint={cost ? `${cost.calls} call(s)` : undefined}
      />
      <div className="bento col-span-2 flex flex-col gap-1 p-4 md:col-span-4">
        <span className="text-xs uppercase tracking-wide text-muted">Cost trend</span>
        <CostSparkline series={series} />
      </div>
    </div>
  );
}
