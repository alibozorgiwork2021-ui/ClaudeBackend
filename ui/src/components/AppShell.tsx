import {
  Activity,
  GitFork,
  ListChecks,
  Rocket,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { useRunStore } from "../store/runStore";
import { humantok, money } from "../lib/format";

const STATUS_COLOR: Record<string, string> = {
  idle: "bg-muted",
  running: "bg-info animate-pulse",
  done: "bg-success",
  error: "bg-danger",
};

function NavItem({ to, icon: Icon, label, end }: { to: string; icon: LucideIcon; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150 cursor-pointer ${
          isActive ? "bg-surface-2 text-fg" : "text-muted hover:text-fg hover:bg-surface"
        }`
      }
    >
      <Icon size={18} aria-hidden />
      <span>{label}</span>
    </NavLink>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const runId = useRunStore((s) => s.runId);
  const status = useRunStore((s) => s.status);
  const lang = useRunStore((s) => s.lang);
  const cost = useRunStore((s) => s.cost);
  const base = runId ? `/runs/${runId}` : null;

  return (
    <div className="flex h-full min-h-dvh">
      <aside className="flex w-56 shrink-0 flex-col gap-1 border-r border-border bg-surface p-3">
        <div className="mb-4 px-2 py-1">
          <div className="text-sm font-600 text-fg">ClaudeBackend</div>
          <div className="text-xs text-muted">dashboard</div>
        </div>
        <NavItem to="/" icon={Rocket} label="Launch" end />
        {base && <NavItem to={base} icon={Activity} label="Live" end />}
        {base && <NavItem to={`${base}/graph`} icon={GitFork} label="Topology" />}
        {base && <NavItem to={`${base}/diff`} icon={ListChecks} label="Diff" />}
        {base && <NavItem to={`${base}/review`} icon={ShieldCheck} label="Review" />}
        <div className="mt-auto px-2 text-[11px] leading-relaxed text-muted">
          Loopback-only · air-gapped. All effects land on an isolated feature branch.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-4 border-b border-border bg-surface/60 px-5 py-3">
          <span className="flex items-center gap-2 text-sm">
            <span className={`h-2.5 w-2.5 rounded-full ${STATUS_COLOR[status]}`} aria-hidden />
            <span className="text-muted">{status}</span>
          </span>
          {runId && (
            <span className="num text-xs text-muted">
              run {runId}
              {lang ? ` · ${lang}` : ""}
            </span>
          )}
          <span className="ml-auto num text-xs text-muted">
            {cost
              ? `${humantok(cost.input_tokens)} in · ${humantok(cost.output_tokens)} out · ${
                  cost.pricing_known ? money(cost.cost_usd) : "pricing unknown"
                }`
              : "no cost yet"}
          </span>
        </header>
        <main className="min-w-0 flex-1 overflow-auto p-5">{children}</main>
      </div>
    </div>
  );
}
