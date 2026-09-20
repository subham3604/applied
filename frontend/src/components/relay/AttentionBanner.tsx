import { useEffect, useState, useTransition } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  X,
  CheckCircle2,
  ArrowRight,
  Sparkles,
  Layers,
  ListFilter,
  RefreshCw,
} from "lucide-react";
import { useRouter } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { type Application } from "@/lib/relay-data";
import {
  type AttentionItem,
  fetchAttentionItems,
  assignAttentionItem,
  createAppFromAttention,
  dismissAttentionItem,
  seedDemoAttention,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STAGE_OPTIONS = [
  { id: "interview", label: "Interview Rounds", backend: "INTERVIEW_ROUND", isDetected: true },
  { id: "oa", label: "OA Pending", backend: "OA_PENDING" },
  { id: "offer", label: "Offer", backend: "OFFER" },
  { id: "applied", label: "Applied", backend: "APPLIED" },
] as const;

export function AttentionBanner({
  applications = [],
  onResolved,
}: {
  applications?: Application[];
  onResolved?: () => void;
}) {
  const router = useRouter();
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isOpen, setIsOpen] = useState(true);
  const [viewMode, setViewMode] = useState<"deck" | "list">("deck");
  const [isExiting, setIsExiting] = useState(false);
  const [isActionPending, setIsActionPending] = useState(false);

  // Per-item selection states keyed by item.id
  const [selectedAppMap, setSelectedAppMap] = useState<Record<string, string>>({});
  const [selectedStageMap, setSelectedStageMap] = useState<Record<string, string>>({});

  const isDemoMode =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("demo") === "true";

  // Load items from live backend queue
  async function loadAttentionQueue() {
    try {
      setIsLoading(true);
      const data = await fetchAttentionItems(isDemoMode);

      if (data.length === 0 && isDemoMode) {
        await seedDemoAttention();
        const seeded = await fetchAttentionItems(true);
        setItems(seeded);
      } else {
        setItems(data);
      }
    } catch (err) {
      console.warn("Could not fetch attention queue from backend:", err);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadAttentionQueue();
  }, []);

  // Filter out demo-seeded items unless ?demo=true is present in the URL
  const displayItems = items.filter((it) => {
    if (it.source === "DEMO") return isDemoMode;
    if (
      it.sender === "recruiting@bundltechnologies.com" ||
      it.sender === "talent-team@stripe.com"
    ) {
      return isDemoMode;
    }
    return true;
  });

  // Safe current index clamp
  const safeIndex = displayItems.length > 0 ? Math.min(currentIndex, displayItems.length - 1) : 0;
  const currentItem = displayItems[safeIndex];

  // Derive candidate applications for a given item
  function getCandidateApps(item: AttentionItem): { id: string; company: string; role: string }[] {
    if (item.candidate_applications && item.candidate_applications.length > 0) {
      return item.candidate_applications;
    }
    // Match by detected company
    if (item.detected_company) {
      const match = applications.filter((a) =>
        a.company.toLowerCase().includes(item.detected_company!.toLowerCase())
      );
      if (match.length > 0) {
        return match.map((a) => ({ id: a.id, company: a.company, role: a.role }));
      }
    }
    // Fallback to top applications
    return applications.slice(0, 3).map((a) => ({ id: a.id, company: a.company, role: a.role }));
  }

  // Pre-select defaults when an item appears
  useEffect(() => {
    if (!currentItem) return;
    const candidates = getCandidateApps(currentItem);
    const defaultAppId = candidates.length > 0 ? candidates[0].id : applications[0]?.id || "";
    
    // Map suggested stage from item or default to interview
    let defaultStage = "interview";
    if (currentItem.suggested_stage) {
      const matched = STAGE_OPTIONS.find(
        (s) => s.backend === currentItem.suggested_stage || s.id === currentItem.suggested_stage.toLowerCase()
      );
      if (matched) defaultStage = matched.id;
    }

    setSelectedAppMap((prev) => ({
      ...prev,
      [currentItem.id]: prev[currentItem.id] || defaultAppId,
    }));
    setSelectedStageMap((prev) => ({
      ...prev,
      [currentItem.id]: prev[currentItem.id] || defaultStage,
    }));
  }, [currentItem?.id, applications]);

  // Handle resolution (Assign, Create New, Dismiss)
  async function handleAssign(item: AttentionItem) {
    const candidates = getCandidateApps(item);
    const selectedAppId = selectedAppMap[item.id] || candidates[0]?.id || applications[0]?.id;
    const selectedStageId = selectedStageMap[item.id] || "interview";
    const stageCfg = STAGE_OPTIONS.find((s) => s.id === selectedStageId) || STAGE_OPTIONS[0];

    if (!selectedAppId) {
      toast.error("Please select a destination application.");
      return;
    }

    setIsActionPending(true);
    setIsExiting(true);

    try {
      await assignAttentionItem(item.id, selectedAppId, stageCfg.backend);
      const targetApp = applications.find((a) => a.id === selectedAppId);
      toast.success(
        `Disambiguated & moved ${targetApp?.company || "application"} to ${stageCfg.label}!`
      );

      // Smooth step forward: remove resolved item from queue
      setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
        setIsExiting(false);
        onResolved?.();
      }, 250);
    } catch (err: any) {
      console.error("Failed to assign attention item:", err);
      toast.error(err.message || "Failed to commit assignment.");
      setIsExiting(false);
    } finally {
      setIsActionPending(false);
    }
  }

  async function handleDismiss(item: AttentionItem) {
    setIsActionPending(true);
    setIsExiting(true);

    try {
      await dismissAttentionItem(item.id);
      toast("Inbound correspondence dismissed.");

      setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
        setIsExiting(false);
        onResolved?.();
      }, 250);
    } catch (err: any) {
      console.error("Failed to dismiss attention item:", err);
      toast.error(err.message || "Failed to dismiss.");
      setIsExiting(false);
    } finally {
      setIsActionPending(false);
    }
  }

  async function handleCreateNew(item: AttentionItem) {
    const stageId = selectedStageMap[item.id] || "applied";
    const stageCfg = STAGE_OPTIONS.find((s) => s.id === stageId) || STAGE_OPTIONS[3];

    setIsActionPending(true);
    setIsExiting(true);

    try {
      await createAppFromAttention(item.id, {
        company_name: item.detected_company || "Unknown Company",
        role_title: item.detected_role || "Engineering Role",
        status: stageCfg.backend,
      });
      toast.success(`Created new application for ${item.detected_company || "Company"}!`);

      setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
        setIsExiting(false);
        onResolved?.();
      }, 250);
    } catch (err: any) {
      console.error("Failed to create application from triage:", err);
      toast.error(err.message || "Failed to create application.");
      setIsExiting(false);
    } finally {
      setIsActionPending(false);
    }
  }

  // Render individual card content
  function renderCardContent(item: AttentionItem, isDeckTop: boolean = false) {
    const candidates = getCandidateApps(item);
    const selectedAppId = selectedAppMap[item.id] || candidates[0]?.id || applications[0]?.id || "";
    const selectedStageId = selectedStageMap[item.id] || "interview";
    const stageCfg = STAGE_OPTIONS.find((s) => s.id === selectedStageId) || STAGE_OPTIONS[0];

    return (
      <div className="space-y-3 p-3.5">
        {/* Email Header Preview */}
        <div className="rounded-md border border-border/80 bg-background/95 p-3 text-xs shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-1.5 pb-2 border-b border-border/60 text-[11px] text-foreground/80">
            <span className="truncate max-w-[280px]">
              <strong className="text-foreground">From:</strong> {item.sender}
            </span>
            <span className="text-warning text-[10px] font-medium bg-warning/15 px-2 py-0.5 rounded border border-warning/30 shrink-0">
              ⚠️ {item.resolution_confidence === "AMBIGUOUS" ? "Ambiguous Correspondence" : "Manual Review Required"}
            </span>
          </div>

          <p className="pt-2 font-medium text-foreground text-xs leading-snug">
            <strong>Subject:</strong> {item.subject}
          </p>

          {item.resolution_note && (
            <p className="mt-1 text-[11px] text-warning/90 italic">
              ↳ Note: {item.resolution_note}
            </p>
          )}

          <p className="mt-2 text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap bg-surface/60 p-2.5 rounded border border-border/50 font-mono text-[11.5px]">
            "{item.raw_body}"
          </p>
        </div>

        {/* Interactive Controls */}
        <div className="space-y-2.5 pt-1">
          {/* Target Application Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold text-foreground/90 mr-1 shrink-0">
              Target Application:
            </span>
            {candidates.map((a) => {
              const isSelected = selectedAppId === a.id;
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setSelectedAppMap((prev) => ({ ...prev, [item.id]: a.id }))}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-all border",
                    isSelected
                      ? "bg-foreground text-background border-foreground font-semibold shadow-sm"
                      : "bg-surface/80 text-foreground/80 border-border hover:bg-elevated hover:text-foreground"
                  )}
                >
                  {isSelected && <CheckCircle2 className="size-3 shrink-0" />}
                  <span>{a.company} ({a.role})</span>
                </button>
              );
            })}
          </div>

          {/* Target Stage Selector */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold text-foreground/90 mr-1 shrink-0">
              Move to Stage:
            </span>
            {STAGE_OPTIONS.map((s) => {
              const isSelected = selectedStageId === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedStageMap((prev) => ({ ...prev, [item.id]: s.id }))}
                  className={cn(
                    "flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors border",
                    isSelected
                      ? "bg-ai text-ai-foreground border-ai font-semibold shadow-sm"
                      : "bg-surface/80 text-muted-foreground border-border hover:text-foreground hover:bg-elevated"
                  )}
                >
                  {"isDetected" in s && s.isDetected && <Sparkles className="size-3 text-warning" />}
                  <span>{s.label}</span>
                </button>
              );
            })}
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2 pt-1.5 border-t border-warning/20">
            <Button
              size="sm"
              disabled={isActionPending}
              className="h-8 text-xs font-semibold gap-1.5 bg-primary text-primary-foreground shadow-sm hover:brightness-95 active:scale-[0.98] transition-all cursor-pointer"
              onClick={() => handleAssign(item)}
            >
              <CheckCircle2 className="size-3.5" />
              Assign & Move to {stageCfg.label}
            </Button>

            <Button
              size="sm"
              variant="subtle"
              disabled={isActionPending}
              className="h-8 text-xs gap-1"
              onClick={() => handleCreateNew(item)}
            >
              <ArrowRight className="size-3" />
              Create as New Application
            </Button>

            <Button
              size="sm"
              variant="ghost"
              disabled={isActionPending}
              className="h-8 text-xs text-muted-foreground ml-auto hover:text-foreground"
              onClick={() => handleDismiss(item)}
            >
              <X className="size-3.5" /> Dismiss
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // If no items in queue to display, return null
  if (displayItems.length === 0) return null;

  return (
    <div className="relative mb-3">
      {/* Deck Header Bar */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-t-lg border border-warning/40 bg-warning/20 dark:bg-warning/25 shadow-sm">
        <button
          type="button"
          onClick={() => setIsOpen((v) => !v)}
          className="flex items-center gap-2 text-left cursor-pointer focus:outline-none"
        >
          <AlertTriangle className="size-4 text-warning shrink-0 animate-pulse" />
          <span className="text-xs font-bold tracking-tight text-warning">
            Action Required: Inbound Correspondence ({safeIndex + 1} of {displayItems.length})
          </span>
          <ChevronDown
            className={cn(
              "size-4 text-warning transition-transform duration-200",
              isOpen && "rotate-180"
            )}
          />
        </button>

        {/* Header Controls: Stack navigation & List View toggle */}
        <div className="flex items-center gap-1.5">
          {displayItems.length > 1 && viewMode === "deck" && (
            <div className="flex items-center gap-0.5 bg-surface/70 px-1 py-0.5 rounded border border-border/60">
              <button
                type="button"
                onClick={() => setCurrentIndex((idx) => Math.max(0, idx - 1))}
                disabled={safeIndex === 0}
                title="Previous correspondence"
                className="p-1 rounded text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="size-3.5" />
              </button>
              <span className="text-[11px] font-mono px-1 font-semibold text-foreground/80">
                {safeIndex + 1}/{displayItems.length}
              </span>
              <button
                type="button"
                onClick={() => setCurrentIndex((idx) => Math.min(displayItems.length - 1, idx + 1))}
                disabled={safeIndex === displayItems.length - 1}
                title="Next correspondence"
                className="p-1 rounded text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <ChevronRight className="size-3.5" />
              </button>
            </div>
          )}

          {displayItems.length > 1 && (
            <button
              type="button"
              onClick={() => setViewMode((m) => (m === "deck" ? "list" : "deck"))}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium text-warning hover:text-warning/80 bg-warning/10 hover:bg-warning/20 border border-warning/30 rounded transition-colors"
              title={viewMode === "deck" ? "Show all cards in scrollable view" : "Switch to stacked card deck view"}
            >
              {viewMode === "deck" ? (
                <>
                  <ListFilter className="size-3" />
                  <span>Show All ({displayItems.length})</span>
                </>
              ) : (
                <>
                  <Layers className="size-3" />
                  <span>Deck View</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Expanded Content */}
      {isOpen && (
        <div className="relative">
          {viewMode === "deck" ? (
            /* ============================================================== */
            /* 1. STACKED DECK VIEW (Physical Cards with Layered Shadows)     */
            /* ============================================================== */
            <div className="relative pt-1 pb-4">
              {/* Layer 2 Shadow Card (3rd in queue) */}
              {displayItems.length > safeIndex + 2 && (
                <div
                  className="absolute inset-x-3 top-5 h-20 rounded-b-lg border border-warning/20 bg-warning/5 dark:bg-warning/10 opacity-40 transform translate-y-3 scale-[0.96] transition-all duration-300 pointer-events-none z-0"
                  aria-hidden="true"
                />
              )}

              {/* Layer 1 Shadow Card (2nd in queue) */}
              {displayItems.length > safeIndex + 1 && (
                <div
                  className="absolute inset-x-1.5 top-3 h-20 rounded-b-lg border border-warning/30 bg-warning/10 dark:bg-warning/15 opacity-70 transform translate-y-1.5 scale-[0.98] transition-all duration-300 pointer-events-none z-10"
                  aria-hidden="true"
                />
              )}

              {/* Primary Active Card (Top of Stack) */}
              <div
                className={cn(
                  "relative z-20 rounded-b-lg border-x border-b border-warning/40 bg-surface/95 dark:bg-surface/90 backdrop-blur-sm shadow-md transition-all duration-300",
                  isExiting && "-translate-y-3 opacity-0 scale-95"
                )}
              >
                {currentItem && renderCardContent(currentItem, true)}
              </div>

              {/* Queue Depth Hint */}
              {displayItems.length > 3 && (
                <div className="text-center pt-2 text-[10px] text-muted-foreground font-mono">
                  +{displayItems.length - 1} more ambiguous inbound messages in queue
                </div>
              )}
            </div>
          ) : (
            /* ============================================================== */
            /* 2. SHOW ALL VIEW (Scrollable list capped with custom scrollbar) */
            /* ============================================================== */
            <div className="rounded-b-lg border-x border-b border-warning/40 bg-surface/90 p-2.5 shadow-inner">
              <div
                className="max-h-[520px] overflow-y-auto pr-1 space-y-3 scrollbar-thin scrollbar-thumb-warning/30 hover:scrollbar-thumb-warning/50 transition-colors"
                style={{ scrollbarGutter: "stable" }}
              >
                {displayItems.map((item, idx) => (
                  <div
                    key={item.id}
                    className="rounded-lg border border-warning/35 bg-background/95 shadow-sm overflow-hidden"
                  >
                    <div className="flex items-center justify-between px-3 py-1.5 bg-warning/10 border-b border-warning/20 text-xs">
                      <span className="font-semibold text-warning">
                        Card #{idx + 1}: {item.detected_company || item.sender}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {item.created_at ? new Date(item.created_at).toLocaleDateString() : ""}
                      </span>
                    </div>
                    {renderCardContent(item, false)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

