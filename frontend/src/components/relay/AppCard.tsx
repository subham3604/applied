import { Clock, Flame, Eye, PenLine, ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Application } from "@/lib/relay-data";
import { formatApplied } from "@/lib/date-format";

const sourceTone: Record<string, "info" | "muted" | "ai"> = {
  Naukri: "info",
  LinkedIn: "info",
  "Gmail Auto": "ai",
  Manual: "muted",
  Direct: "muted",
};

export function AppCard({
  app,
  onOpen,
}: {
  app: Application;
  onOpen: (app: Application) => void;
}) {
  const appliedDisplay = formatApplied(app.applied, app.applied_at);

  return (
    <article
      onClick={() => onOpen(app)}
      className="group flex h-[142px] cursor-pointer flex-col justify-between rounded-lg border border-border bg-surface p-3 shadow-sm transition-colors hover:border-ai/55 hover:bg-elevated"
    >
      <div>
        {/* Company & Role Header */}
        <div className="flex items-start gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-md border border-border bg-elevated text-xs font-semibold">
            {app.company.slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <h3 className="truncate text-sm font-semibold leading-tight">{app.company}</h3>
              {app.priority && <Flame className="size-3.5 shrink-0 text-warning" />}
            </div>
            <p className="truncate text-xs text-muted-foreground">{app.role}</p>
          </div>
          <Badge variant={sourceTone[app.source] ?? "muted"} className="shrink-0 px-1.5 py-0 text-[10px]">
            {app.source}
          </Badge>
        </div>

        {/* Info Row: Applied time on left, Deadline badge on right */}
        <div className="mt-2.5 flex h-5 items-center justify-between gap-1.5 text-[11px] text-muted-foreground">
          <div className="flex min-w-0 items-center gap-1.5">
            <Clock className="size-3 shrink-0" />
            <span className="truncate">{appliedDisplay}</span>
          </div>
          {app.deadline && (
            <Badge variant={app.deadlineTone ?? "warning"} className="shrink-0 px-1.5 py-0 text-[10px]">
              {app.deadline}
            </Badge>
          )}
        </div>

        {/* Stack Tags Row: always h-5, never wrapping */}
        <div className="mt-1.5 flex h-5 items-center gap-1 overflow-hidden">
          {app.stack && app.stack.length > 0 ? (
            <>
              {app.stack.slice(0, 3).map((t) => (
                <span
                  key={t}
                  className="shrink-0 rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                >
                  {t}
                </span>
              ))}
              {app.stack.length > 3 && (
                <span className="shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  +{app.stack.length - 3}
                </span>
              )}
            </>
          ) : (
            <span className="font-mono text-[10px] italic text-muted-foreground/40">
              Standard Track
            </span>
          )}
        </div>
      </div>

      {/* Stable Action Footer: zero hover jitter, reserved height */}
      <div className="flex h-6 items-center justify-between border-t border-border/50 pt-1 text-[11px] text-muted-foreground">
        <div className="flex items-center gap-2.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
          <span className="inline-flex items-center gap-1 hover:text-foreground">
            <Eye className="size-3" /> Snapshot
          </span>
          <span className="inline-flex items-center gap-1 hover:text-foreground">
            <PenLine className="size-3" /> Override
          </span>
        </div>
        <span className="inline-flex items-center gap-0.5 text-ai opacity-70 transition-opacity duration-150 group-hover:opacity-100">
          Open <ArrowUpRight className="size-3" />
        </span>
      </div>
    </article>
  );
}
