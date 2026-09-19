import { useEffect, useState } from "react";
import { AlertTriangle, ChevronDown, X, CheckCircle2, ArrowRight, Sparkles } from "lucide-react";
import { useRouter } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { type Application } from "@/lib/relay-data";
import { overrideStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

export const STORAGE_KEY = "relay_ambiguous_banner_resolved";

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
  const [open, setOpen] = useState(true);
  const [isDismissed, setIsDismissed] = useState(true);
  const [isResolving, setIsResolving] = useState(false);

  // Find Swiggy / Bundl applications, or fallback to first 3 applications
  const matchingApps = applications.filter(
    (a) =>
      a.company.toLowerCase().includes("swiggy") ||
      a.company.toLowerCase().includes("bundl"),
  );
  const candidateApps = matchingApps.length > 0 ? matchingApps : applications.slice(0, 3);

  const [selectedAppId, setSelectedAppId] = useState<string>("");
  const [selectedStage, setSelectedStage] = useState<string>("interview");

  useEffect(() => {
    const resolved = localStorage.getItem(STORAGE_KEY);
    if (resolved === "true") {
      setIsDismissed(true);
    } else {
      setIsDismissed(candidateApps.length === 0);
    }
  }, [candidateApps.length]);

  useEffect(() => {
    if (candidateApps.length > 0 && (!selectedAppId || !candidateApps.some((a) => a.id === selectedAppId))) {
      setSelectedAppId(candidateApps[0].id);
    }
  }, [candidateApps, selectedAppId]);

  if (isDismissed || candidateApps.length === 0) return null;

  const targetApp = candidateApps.find((a) => a.id === selectedAppId) || candidateApps[0];
  const stageConfig = STAGE_OPTIONS.find((s) => s.id === selectedStage) || STAGE_OPTIONS[0];

  async function handleAssign() {
    if (!targetApp) {
      toast.error("Please select a destination application.");
      return;
    }

    setIsResolving(true);
    try {
      await overrideStatus(
        targetApp.id,
        stageConfig.backend,
        `Inbound email from Bundl Technologies (Swiggy) assigned to ${targetApp.company} (${targetApp.role}) -> stage: ${stageConfig.label}.`,
      );
      toast.success(`Assigned email to ${targetApp.company} and updated stage to ${stageConfig.label}!`);
      localStorage.setItem(STORAGE_KEY, "true");
      setIsDismissed(true);
      onResolved?.();
    } catch (err: any) {
      console.error("Failed to assign ambiguous email:", err);
      toast.error(err.message || "Failed to commit assignment to backend.");
    } finally {
      setIsResolving(false);
    }
  }

  function handleDismiss() {
    localStorage.setItem(STORAGE_KEY, "true");
    setIsDismissed(true);
    toast("Ambiguous email notification dismissed.");
  }

  function handleCreateNew() {
    localStorage.setItem(STORAGE_KEY, "true");
    setIsDismissed(true);
    router.navigate({ to: "/new-drop" });
  }

  return (
    <div className="rounded-lg border border-warning/40 bg-warning/15">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <AlertTriangle className="size-4 text-warning shrink-0" />
        <span className="text-xs font-semibold text-warning">
          Action Required: Inbound Email from “Bundl Technologies” (Swiggy)
        </span>
        <ChevronDown
          className={cn(
            "ml-auto size-4 text-warning transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="space-y-3 border-t border-warning/30 px-3 py-3">
          {/* Inbound Email Body Preview */}
          <div className="rounded-md border border-border/80 bg-background/90 p-3 font-mono text-xs text-muted-foreground shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-1 pb-1.5 border-b border-border/60 text-[11px] font-sans text-foreground/80">
              <span>
                <strong>From:</strong> recruiting@bundltechnologies.com
              </span>
              <span className="text-warning text-[10px] font-medium bg-warning/10 px-1.5 py-0.5 rounded border border-warning/30">
                ⚠️ Matching Confirmation Needed
              </span>
            </div>
            <p className="pt-1.5 font-sans font-medium text-foreground/90 text-xs">
              <strong>Subject:</strong> Next steps regarding your application at Bundl Technologies (Swiggy)
            </p>
            <p className="mt-1.5 font-sans text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap bg-surface/50 p-2 rounded border border-border/40">
              "Hi candidate, thank you for your application to Bundl Technologies (Swiggy). We were impressed with your engineering background and would like to schedule a technical discussion regarding your candidacy. Please confirm which application and stage to update."
            </p>
          </div>

          {/* Interactive Assignment Controls */}
          <div className="space-y-2.5 pt-1">
            {/* 1. Destination Application Selection */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium text-foreground/85 mr-1">
                Target Application:
              </span>
              {candidateApps.map((a) => {
                const isSelected = selectedAppId === a.id;
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => setSelectedAppId(a.id)}
                    className={cn(
                      "flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors border",
                      isSelected
                        ? "bg-foreground text-background border-foreground font-semibold shadow-sm"
                        : "bg-surface text-foreground/80 border-border hover:bg-elevated hover:text-foreground"
                    )}
                  >
                    {isSelected && <CheckCircle2 className="size-3" />}
                    <span>{a.company} ({a.role})</span>
                  </button>
                );
              })}
            </div>

            {/* 2. Target Stage Selection */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium text-foreground/85 mr-1">
                Move to Stage:
              </span>
              {STAGE_OPTIONS.map((s) => {
                const isSelected = selectedStage === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setSelectedStage(s.id)}
                    className={cn(
                      "flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors border",
                      isSelected
                        ? "bg-ai text-ai-foreground border-ai font-semibold shadow-sm"
                        : "bg-surface text-muted-foreground border-border hover:text-foreground hover:bg-elevated"
                    )}
                  >
                    {"isDetected" in s && s.isDetected && <Sparkles className="size-3 text-warning" />}
                    <span>{s.label}</span>
                  </button>
                );
              })}
            </div>

            {/* 3. Action Buttons */}
            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-warning/20">
              <Button
                size="sm"
                disabled={isResolving}
                className="h-8 text-xs font-semibold gap-1.5 bg-primary text-primary-foreground shadow-sm hover:brightness-90 dark:hover:brightness-110 active:scale-[0.98] transition-all cursor-pointer"
                onClick={handleAssign}
              >
                <CheckCircle2 className="size-3.5" />
                Assign & Move to {stageConfig.label}
              </Button>

              <Button
                size="sm"
                variant="subtle"
                disabled={isResolving}
                className="h-8 text-xs gap-1"
                onClick={handleCreateNew}
              >
                <ArrowRight className="size-3" />
                Create New Application
              </Button>

              <Button
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-muted-foreground ml-auto hover:text-foreground"
                onClick={handleDismiss}
              >
                <X className="size-3.5" /> Dismiss
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
