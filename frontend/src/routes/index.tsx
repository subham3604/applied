import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Search, RefreshCw, AlertCircle, X, RotateCcw } from "lucide-react";
import { TopNav } from "@/components/relay/TopNav";
import { AttentionBanner } from "@/components/relay/AttentionBanner";
import { AppCard } from "@/components/relay/AppCard";
import { DetailDrawer } from "@/components/relay/DetailDrawer";
import { Toaster } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { STAGES, type Application } from "@/lib/relay-data";
import { fetchApplications, fetchMetrics, type PipelineMetrics } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Applied — Pipeline Dashboard" },
      {
        name: "description",
        content:
          "Applied is an AI-powered autonomous job application tracker: a Kanban pipeline fed by a daily Gmail worker and grounded resume snapshots.",
      },
      { property: "og:title", content: "Applied — Pipeline Dashboard" },
      {
        property: "og:description",
        content: "Track every application stage from applied to offer, with an append-only audit trail.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Pipeline,
});

const FILTERS = ["All", "High Priority", "Active", "Archived"] as const;

function Pipeline() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [active, setActive] = useState<Application | null>(null);

  const [applications, setApplications] = useState<Application[]>([]);
  const [metrics, setMetrics] = useState<PipelineMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [apps, m] = await Promise.all([
        fetchApplications(),
        fetchMetrics(),
      ]);
      setApplications(apps);
      setMetrics(m);
    } catch (err: any) {
      console.error("Failed to load pipeline data:", err);
      const msg = "Unable to connect to server. Please ensure the service is running.";
      setError(msg);
      toast.error("Could not load applications from server. Please check your connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleReset = useCallback(async () => {
    setQuery("");
    setFilter("All");
    localStorage.removeItem("relay_ambiguous_banner_resolved");
    await loadData();
    toast.success("Filters reset & pipeline reloaded");
  }, [loadData]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const stats = useMemo(() => {
    const activeCount = metrics
      ? (metrics.total_active ?? (metrics.total - metrics.rejected))
      : applications.filter((a) => a.stage !== "rejected").length;

    const oaCount = metrics
      ? metrics.pending_oa
      : applications.filter((a) => a.stage === "oa").length;

    const interviewCount = metrics
      ? metrics.active_interviews
      : applications.filter((a) => a.stage === "interview").length;

    const offerCount = metrics
      ? metrics.offers
      : applications.filter((a) => a.stage === "offer").length;

    const rejectedCount = metrics
      ? metrics.rejected
      : applications.filter((a) => a.stage === "rejected").length;

    return [
      {
        label: "Total Active",
        value: activeCount,
        tone: "text-foreground",
      },
      {
        label: "OAs Pending",
        value: oaCount,
        tone: "text-warning",
      },
      {
        label: "Interviews",
        value: interviewCount,
        tone: "text-info",
      },
      {
        label: "Offers",
        value: offerCount,
        tone: "text-success",
      },
      {
        label: "Rejected / Withdrawn",
        value: rejectedCount,
        tone: "text-muted-foreground",
      },
    ];
  }, [metrics, applications]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return applications.filter((a) => {
      const haystack = `${a.company} ${a.role} ${(a.stack || []).join(" ")}`.toLowerCase();
      if (q && !haystack.includes(q)) return false;
      if (filter === "High Priority") return !!a.priority;
      if (filter === "Active") return a.stage !== "rejected";
      if (filter === "Archived") return a.stage === "rejected";
      return true;
    });
  }, [applications, query, filter]);

  const currentActiveApp = useMemo(() => {
    if (!active) return null;
    return applications.find((a) => a.id === active.id) ?? active;
  }, [active, applications]);

  return (
    <div className="min-h-screen">
      <TopNav />

      <main className="mx-auto max-w-[1600px] px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          {stats.map((s) => (
            <div
              key={s.label}
              className="flex items-baseline gap-2 rounded-lg border border-border bg-surface px-3 py-2"
            >
              <span className={cn("text-lg font-semibold tabular-nums", s.tone)}>{s.value}</span>
              <span className="text-[11px] text-muted-foreground">{s.label}</span>
            </div>
          ))}

          <div className="ml-auto flex w-full items-center gap-2 sm:w-auto">
            <div className="relative flex-1 sm:w-72">
              <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              <input
                ref={searchInputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search company, role, stack…"
                className="h-9 w-full rounded-md border border-input bg-surface pl-8 pr-16 text-xs outline-none placeholder:text-muted-foreground focus:border-ring"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="absolute right-9 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5 rounded transition-colors"
                  title="Clear search query"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
              <kbd
                onClick={() => searchInputRef.current?.focus()}
                className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer rounded border border-border bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground hover:text-foreground"
                title="Press ⌘K to search"
              >
                ⌘K
              </kbd>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              disabled={loading}
              className="h-9 px-2.5 text-xs text-muted-foreground hover:text-foreground gap-1.5"
            >
              <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
              <span className="hidden sm:inline">Reset</span>
            </Button>
          </div>
        </div>

        {error && (
          <div className="mt-3 flex items-center justify-between rounded-lg border border-warning/30 bg-warning/10 px-4 py-2.5 text-xs text-warning">
            <div className="flex items-center gap-2">
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={loadData}
              className="h-7 text-xs text-warning hover:bg-warning/20"
            >
              Retry Connection
            </Button>
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <Button
              key={f}
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setFilter(f)}
              className={cn(
                "h-7 rounded-full border px-3 text-[11px] shadow-none transition-colors",
                filter === f
                  ? "border-ai/50 bg-ai/15 text-ai"
                  : "border-border bg-surface text-muted-foreground hover:text-foreground",
              )}
            >
              {f}
            </Button>
          ))}
        </div>

        <div className="mt-4">
          <AttentionBanner applications={applications} onResolved={loadData} />
        </div>

        <div className="mt-4 grid items-start gap-3 md:grid-cols-2 xl:grid-cols-5">
          {STAGES.map((stage) => {
            const cards = visible.filter((a) => a.stage === stage.id);
            return (
              <section
                key={stage.id}
                className={cn(
                  "flex max-h-[calc(100vh-290px)] min-h-40 flex-col overflow-hidden rounded-lg border",
                  stage.id === "applied" && "border-info/30 bg-info/10",
                  stage.id === "oa" && "border-warning/30 bg-warning/10",
                  stage.id === "interview" && "border-ai/30 bg-ai/10",
                  stage.id === "offer" && "border-success/30 bg-success/10",
                  stage.id === "rejected" && "border-danger/25 bg-danger/10",
                )}
              >
                <header className="flex shrink-0 items-center gap-2 border-b border-border bg-surface/60 px-3 py-2 backdrop-blur">
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      stage.id === "applied" && "bg-info",
                      stage.id === "oa" && "bg-warning",
                      stage.id === "interview" && "bg-ai",
                      stage.id === "offer" && "bg-success",
                      stage.id === "rejected" && "bg-danger",
                    )}
                  />
                  <h2 className="text-xs font-semibold">{stage.label}</h2>
                  <span className="rounded bg-elevated px-1.5 text-[10px] tabular-nums text-muted-foreground">
                    {cards.length}
                  </span>
                </header>
                
                {loading && applications.length === 0 ? (
                  <div className="flex flex-col gap-2 p-2">
                    <Skeleton className="h-28 w-full rounded-md" />
                    <Skeleton className="h-28 w-full rounded-md" />
                  </div>
                ) : (
                  <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2 scroll-thin">
                    {cards.map((a) => (
                      <AppCard key={a.id} app={a} onOpen={setActive} />
                    ))}
                    {cards.length === 0 && (
                      <p className="px-1 py-4 text-center text-[11px] text-muted-foreground">
                        {stage.hint}
                      </p>
                    )}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </main>

      <DetailDrawer
        app={currentActiveApp}
        onClose={() => setActive(null)}
        onUpdated={() => {
          loadData();
        }}
      />
      <Toaster />
    </div>
  );
}
