import { useEffect, useState } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/relay/ThemeToggle";
import { fetchWorkerStatus, type WorkerStatus } from "@/lib/api";
import { formatTimelineDate } from "@/lib/date-format";

const links = [
  { to: "/", label: "Pipeline" },
  { to: "/new-drop", label: "New Drop" },
  { to: "/vault", label: "Vault" },
] as const;

export function TopNav() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null);

  useEffect(() => {
    fetchWorkerStatus()
      .then(setWorkerStatus)
      .catch((err) => console.warn("Could not fetch worker status:", err));
  }, []);

  const syncDisplay = workerStatus?.last_synced_at
    ? formatTimelineDate(undefined, workerStatus.last_synced_at).display
    : "Recently";

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2">
          <span className="grid size-7 place-items-center rounded-md bg-ai/15 text-ai shadow-sm">
            <Radio className="size-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Applied</span>
        </Link>

        <nav className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
          {links.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                path === l.to
                  ? "bg-elevated text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <div className="hidden items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 sm:flex">
            <span className="relative grid size-2 place-items-center">
              <span
                className={cn(
                  "pulse-dot absolute inset-0 rounded-full",
                  workerStatus?.active !== false ? "bg-success" : "bg-muted-foreground",
                )}
              />
            </span>
            <span className="text-[11px] text-muted-foreground">
              <span className="text-foreground">Gmail Sync: Active</span>
              <span className="hidden sm:inline"> · Last synced {syncDisplay}</span>
            </span>
          </div>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
