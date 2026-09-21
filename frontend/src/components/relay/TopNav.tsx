import { useEffect, useState } from "react";
import { Link, useRouter, useRouterState } from "@tanstack/react-router";
import { Radio, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/relay/ThemeToggle";
import { fetchWorkerStatus, triggerWorkerSync, type WorkerStatus } from "@/lib/api";
import { formatTimelineDate } from "@/lib/date-format";

const links = [
  { to: "/", label: "Pipeline" },
  { to: "/new-drop", label: "New Drop" },
  { to: "/vault", label: "Vault" },
] as const;

export function TopNav() {
  const router = useRouter();
  const path = useRouterState({ select: (s) => s.location.pathname });
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  function loadStatus() {
    fetchWorkerStatus()
      .then(setWorkerStatus)
      .catch((err) => console.warn("Could not fetch worker status:", err));
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function handleSyncNow() {
    if (isSyncing) return;
    setIsSyncing(true);
    toast.info("Connecting to Gmail and running autonomous pipeline...");

    try {
      const res = await triggerWorkerSync();
      const summary = res.summary || {};
      const processed = summary.processed ?? 0;
      const relevant = summary.relevant ?? 0;
      const committed = summary.committed ?? 0;

      toast.success(
        `Gmail sync complete: Processed ${processed} emails (${relevant} relevant, ${committed} committed)!`
      );
      loadStatus();
      router.invalidate();
    } catch (err: any) {
      console.error("Gmail sync failed:", err);
      toast.error(err.message || "Failed to sync Gmail. Check credentials on Render.");
    } finally {
      setIsSyncing(false);
    }
  }

  const syncDisplay = workerStatus?.last_synced_at
    ? `Last synced ${formatTimelineDate(undefined, workerStatus.last_synced_at).display}`
    : "Not synced yet";

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
          {/* Gmail Sync Status & Interactive Trigger */}
          <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 text-xs shadow-xs">
            <span className="relative grid size-2 place-items-center ml-0.5">
              <span
                className={cn(
                  "pulse-dot absolute inset-0 rounded-full",
                  workerStatus?.active !== false ? "bg-success" : "bg-muted-foreground",
                )}
              />
            </span>
            <span className="hidden text-[11px] text-muted-foreground md:inline">
              <span className="text-foreground font-medium">Gmail Sync</span>
              <span> · {syncDisplay}</span>
            </span>

            <button
              type="button"
              onClick={handleSyncNow}
              disabled={isSyncing}
              title="Sync Gmail inbox now"
              className={cn(
                "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold transition-all border cursor-pointer",
                isSyncing
                  ? "bg-warning/15 text-warning border-warning/30"
                  : "bg-elevated hover:bg-border text-foreground border-border/80"
              )}
            >
              <RefreshCw className={cn("size-3", isSyncing && "animate-spin text-warning")} />
              <span>{isSyncing ? "Syncing…" : "Sync Now"}</span>
            </button>
          </div>

          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

