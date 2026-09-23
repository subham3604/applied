import { useState, useEffect } from "react";
import {
  Bot,
  User,
  Zap,
  ChevronDown,
  Copy,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Clock,
  Edit3,
  Save,
  RotateCcw,
  FilePlus,
} from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { toast } from "sonner";
import { STAGES, type Application, type TimelineEvent, type Stage } from "@/lib/relay-data";
import {
  overrideStatus,
  updatePortalText,
  updateResume,
  updateApplication,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatApplied, formatTimelineDate } from "@/lib/date-format";
import { MarkdownViewer } from "./MarkdownViewer";

const originMeta = {
  worker: { label: "Gmail Worker", Icon: Bot, tone: "ai" as const },
  manual: { label: "Manual Drop", Icon: User, tone: "info" as const },
  override: { label: "Direct Override", Icon: Zap, tone: "warning" as const },
};

function TimelineRow({ event, last }: { event: TimelineEvent; last: boolean }) {
  const [open, setOpen] = useState(false);
  const meta = originMeta[event.origin] || originMeta.manual;
  const { label, Icon, tone } = meta;
  const timeFormatted = formatTimelineDate(event.date, event.timestamp);

  return (
    <li className="relative pl-9">
      {!last && <span className="absolute left-3.5 top-7 h-[calc(100%-1rem)] w-px bg-border" />}
      <span
        className={cn(
          "absolute left-0 grid size-7 place-items-center rounded-full border bg-surface",
          tone === "ai" && "border-ai/40 text-ai",
          tone === "info" && "border-info/40 text-info",
          tone === "warning" && "border-warning/40 text-warning",
        )}
      >
        <Icon className="size-3.5" />
      </span>
      <div className="pb-5">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium">{event.title}</p>
          <Badge variant={tone} className="px-1.5 py-0 text-[10px]">
            {label}
          </Badge>
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            {timeFormatted.display}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{event.detail}</p>
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />
          Inspect raw payload
        </button>
        {open && (
          <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-background p-2.5 font-mono text-[11px] text-muted-foreground">
            {event.payload}
          </pre>
        )}
      </div>
    </li>
  );
}

const STAGE_TO_BACKEND: Record<string, string> = {
  applied: "APPLIED",
  oa: "OA_PENDING",
  interview: "INTERVIEW_ROUND",
  offer: "OFFER",
  rejected: "REJECTED",
  withdrawn: "WITHDRAWN",
};

export function DetailDrawer({
  app,
  onClose,
  onUpdated,
}: {
  app: Application | null;
  onClose: () => void;
  onUpdated?: () => void;
}) {
  const [showResumeModal, setShowResumeModal] = useState(false);
  const [overrideStage, setOverrideStage] = useState<string>("interview");
  const [forceStage, setForceStage] = useState<string>("applied");
  const [note, setNote] = useState("");
  const [isUpdating, setIsUpdating] = useState(false);

  const [portalText, setPortalText] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // Resume Snapshot Edit State (CUJ-5, FR-04, FR-05)
  const [isEditingResume, setIsEditingResume] = useState(false);
  const [resumeDraft, setResumeDraft] = useState("");
  const [isSavingResume, setIsSavingResume] = useState(false);

  // Application details edit state
  const [isEditingDetails, setIsEditingDetails] = useState(false);
  const [editCompany, setEditCompany] = useState("");
  const [editRole, setEditRole] = useState("");
  const [editLocation, setEditLocation] = useState("");
  const [editStack, setEditStack] = useState("");
  const [editSource, setEditSource] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [isSavingDetails, setIsSavingDetails] = useState(false);

  useEffect(() => {
    if (app) {
      setResumeDraft(app.resume || "");
      setIsEditingResume(false);
      setEditCompany(app.company || "");
      setEditRole(app.role || "");
      setEditLocation(app.location || "");
      setEditStack(Array.isArray(app.stack) ? app.stack.join(", ") : "");
      setEditSource(app.source || "Direct");
      setEditDescription((app as any).job_description_raw || "");
      setIsEditingDetails(false);
    }
  }, [app?.id, app?.resume, app?.company, app?.role, app?.location]);

  async function handleSaveDetails() {
    if (!app) return;
    if (!editCompany.trim() || !editRole.trim()) {
      toast.error("Company name and Role title cannot be empty.");
      return;
    }
    setIsSavingDetails(true);
    try {
      const stackList = editStack
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      await updateApplication(app.id, {
        company_name: editCompany.trim(),
        role_title: editRole.trim(),
        location: editLocation.trim() || undefined,
        primary_tech_stack: stackList,
        source_platform: editSource.trim() || undefined,
        job_description_raw: editDescription.trim() || undefined,
      });

      toast.success("Application details updated successfully!");
      setIsEditingDetails(false);
      onUpdated?.();
    } catch (err: any) {
      console.error("Failed to update application:", err);
      toast.error(err.message || "Failed to update application.");
    } finally {
      setIsSavingDetails(false);
    }
  }

  if (!app) return null;
  const stage = STAGES.find((s) => s.id === app.stage);
  if (!stage) return null;

  async function handleDirectOverride(targetStageKey: string, customNote?: string) {
    if (!app) return;
    const backendStatus = STAGE_TO_BACKEND[targetStageKey] || targetStageKey.toUpperCase();
    setIsUpdating(true);
    try {
      const res = await overrideStatus(app.id, backendStatus, customNote ?? note);
      if (res.success) {
        const friendlyStage = STAGES.find((s) => s.id === targetStageKey)?.label || res.new_status;
        toast.success(`Stage updated to ${friendlyStage}`);
        setNote("");
        onUpdated?.();
      }
    } catch (err: any) {
      console.error("Override error:", err);
      toast.error(err.message || "Failed to update status on backend.");
    } finally {
      setIsUpdating(false);
    }
  }

  async function handlePortalSnippetUpdate() {
    if (!app) return;
    if (!portalText.trim()) {
      toast.error("Please paste a recruiter message or portal update first.");
      return;
    }
    setIsAnalyzing(true);
    try {
      const res = await updatePortalText(app.id, portalText);
      if (res.success) {
        const stageEntry = Object.entries(STAGE_TO_BACKEND).find(([_, v]) => v === res.new_status);
        const friendlyStage = stageEntry ? (STAGES.find((s) => s.id === stageEntry[0])?.label || res.new_status) : res.new_status;
        toast.success(`Message analyzed — stage updated to ${friendlyStage}`);
        setPortalText("");
        onUpdated?.();
      }
    } catch (err: any) {
      console.error("Portal update error:", err);
      toast.error(err.message || "Failed to analyze message.");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleSaveResume() {
    if (!app) return;
    if (!resumeDraft.trim()) {
      toast.error("Resume snapshot content cannot be empty.");
      return;
    }
    setIsSavingResume(true);
    try {
      const res = await updateResume(app.id, resumeDraft);
      if (res.success) {
        toast.success("Resume snapshot saved successfully!");
        setIsEditingResume(false);
        onUpdated?.();
      }
    } catch (err: any) {
      console.error("Failed to update resume snapshot:", err);
      toast.error(err.message || "Failed to save resume snapshot.");
    } finally {
      setIsSavingResume(false);
    }
  }

  function handleCopyResume() {
    const content = isEditingResume ? resumeDraft : (app?.resume || resumeDraft);
    if (!content || !content.trim()) {
      toast.error("No resume snapshot found for this application.");
      return;
    }
    navigator.clipboard?.writeText(content);
    toast.success("Resume markdown copied to clipboard");
  }

  return (
    <>
      <Sheet open={!!app} onOpenChange={(o) => !o && onClose()}>
        <SheetContent className="w-full overflow-y-auto border-border bg-background p-0 scroll-thin sm:max-w-xl">
          <SheetHeader className="sticky top-0 z-10 border-b border-border bg-background/95 p-5 backdrop-blur">
            <div className="flex items-start gap-3">
              <span className="grid size-9 place-items-center rounded-md border border-border bg-surface text-sm font-semibold uppercase">
                {app.company.slice(0, 1)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <SheetTitle className="truncate text-base">{app.company}</SheetTitle>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 gap-1 px-1.5 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setIsEditingDetails(!isEditingDetails)}
                  >
                    <Edit3 className="size-3" />
                    <span className="text-[11px]">{isEditingDetails ? "Cancel" : "Edit"}</span>
                  </Button>
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {app.role} · {app.location || "Remote"}
                </p>
                <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Clock className="size-3 shrink-0" />
                  <span>{formatApplied(app.applied, app.applied_at)}</span>
                </p>
              </div>
            </div>

            {isEditingDetails && (
              <div className="mt-3 space-y-2 rounded-md border border-border bg-surface/50 p-3 text-xs">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-[10px] font-semibold uppercase text-muted-foreground">Company</label>
                    <Input
                      value={editCompany}
                      onChange={(e) => setEditCompany(e.target.value)}
                      placeholder="Company name"
                      className="h-7 text-xs bg-background"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold uppercase text-muted-foreground">Role Title</label>
                    <Input
                      value={editRole}
                      onChange={(e) => setEditRole(e.target.value)}
                      placeholder="Role title"
                      className="h-7 text-xs bg-background"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-[10px] font-semibold uppercase text-muted-foreground">Location</label>
                    <Input
                      value={editLocation}
                      onChange={(e) => setEditLocation(e.target.value)}
                      placeholder="Location (e.g. Remote)"
                      className="h-7 text-xs bg-background"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold uppercase text-muted-foreground">Source</label>
                    <Input
                      value={editSource}
                      onChange={(e) => setEditSource(e.target.value)}
                      placeholder="e.g. LinkedIn, Direct"
                      className="h-7 text-xs bg-background"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] font-semibold uppercase text-muted-foreground">Tech Stack (comma-separated)</label>
                  <Input
                    value={editStack}
                    onChange={(e) => setEditStack(e.target.value)}
                    placeholder="e.g. Python, FastAPI, React"
                    className="h-7 text-xs bg-background"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-semibold uppercase text-muted-foreground">Job Description / Notes</label>
                  <Textarea
                    rows={2}
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder="Role notes or job description..."
                    className="resize-none text-xs bg-background"
                  />
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => setIsEditingDetails(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 gap-1 text-xs"
                    disabled={isSavingDetails}
                    onClick={handleSaveDetails}
                  >
                    {isSavingDetails ? <Loader2 className="size-3 animate-spin" /> : <Save className="size-3" />}
                    Save Changes
                  </Button>
                </div>
              </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  app.stage === "offer"
                    ? "success"
                    : app.stage === "rejected"
                      ? "danger"
                      : app.stage === "oa"
                        ? "warning"
                        : "info"
                }
                className="cursor-pointer"
                onClick={() => toast("Use 'Update Status' below to advance or override the stage")}
              >
                {stage.label}
              </Badge>
              <Button
                size="sm"
                variant="subtle"
                className="ml-auto gap-1 text-xs"
                onClick={() => setShowResumeModal(true)}
              >
                <FileText className="size-3.5" /> View Submitted Resume Snapshot
              </Button>
            </div>
          </SheetHeader>

          <div className="space-y-6 p-5">
            <section>
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Stage History &amp; Audit Trail
              </h4>
              {app.timeline && app.timeline.length > 0 ? (
                <ol>
                  {app.timeline.map((e, i) => (
                    <TimelineRow key={e.id} event={e} last={i === app.timeline.length - 1} />
                  ))}
                </ol>
              ) : (
                <p className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
                  No previous events recorded.
                </p>
              )}
            </section>

            <section className="panel p-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Update Status
              </h4>
              <Tabs defaultValue="override">
                <TabsList className="bg-elevated">
                  <TabsTrigger value="override">Direct Override</TabsTrigger>
                  <TabsTrigger value="paste">Paste Portal Snippet</TabsTrigger>
                </TabsList>

                <TabsContent value="override" className="mt-3 space-y-2.5">
                  <Select value={overrideStage} onValueChange={setOverrideStage}>
                    <SelectTrigger className="bg-background">
                      <SelectValue placeholder="Next stage" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="oa">OA Pending</SelectItem>
                      <SelectItem value="interview">Interview Rounds</SelectItem>
                      <SelectItem value="offer">Offer</SelectItem>
                      <SelectItem value="rejected">Rejected</SelectItem>
                      <SelectItem value="withdrawn">Withdrawn</SelectItem>
                      <SelectItem value="applied">Applied (Reset)</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Optional note (e.g. recruiter call outcome, test link)"
                    className="bg-background"
                  />
                  <Button
                    className="w-full gap-2"
                    disabled={isUpdating}
                    onClick={() => handleDirectOverride(overrideStage)}
                  >
                    {isUpdating && <Loader2 className="size-3.5 animate-spin" />}
                    Update Status
                  </Button>
                </TabsContent>

                <TabsContent value="paste" className="mt-3 space-y-2.5">
                  <Textarea
                    rows={5}
                    value={portalText}
                    onChange={(e) => setPortalText(e.target.value)}
                    placeholder="Paste email / portal update message (e.g. 'Congratulations, you have been shortlisted for technical interview on Google Meet')..."
                    className="resize-none bg-background font-mono text-xs"
                  />
                  <Button
                    variant="ai"
                    className="w-full gap-2"
                    disabled={isAnalyzing}
                    onClick={handlePortalSnippetUpdate}
                  >
                    {isAnalyzing && <Loader2 className="size-3.5 animate-spin" />}
                    Analyze &amp; Update
                  </Button>
                </TabsContent>
              </Tabs>

              <Accordion type="single" collapsible className="mt-3">
                <AccordionItem value="force" className="border-border">
                  <AccordionTrigger className="text-xs text-muted-foreground hover:no-underline">
                    <span className="inline-flex items-center gap-1.5">
                      <AlertTriangle className="size-3.5 text-warning" /> Manual Stage Override
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-2.5">
                    <p className="text-[11px] text-muted-foreground">
                      Manually correct or reset the current stage of this application.
                    </p>
                    <Select value={forceStage} onValueChange={setForceStage}>
                      <SelectTrigger className="bg-background">
                        <SelectValue placeholder="Select stage…" />
                      </SelectTrigger>
                      <SelectContent>
                        {STAGES.map((s) => (
                          <SelectItem key={s.id} value={s.id}>
                            {s.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={isUpdating}
                      onClick={() => handleDirectOverride(forceStage, "Manual stage override")}
                    >
                      Save Override
                    </Button>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </section>

            <section className="panel p-4">
              <div className="mb-3 flex items-center gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Submitted Resume Snapshot
                </h4>
                {!isEditingResume ? (
                  <div className="ml-auto flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="gap-1 text-xs px-2"
                      onClick={() => {
                        setIsEditingResume(true);
                        setResumeDraft(app.resume || "");
                      }}
                    >
                      <Edit3 className="size-3.5" /> Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="gap-1 text-xs px-2"
                      onClick={handleCopyResume}
                    >
                      <Copy className="size-3.5" /> Copy Text
                    </Button>
                  </div>
                ) : (
                  <div className="ml-auto flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="default"
                      className="gap-1 text-xs"
                      disabled={isSavingResume}
                      onClick={handleSaveResume}
                    >
                      {isSavingResume ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Save className="size-3.5" />
                      )}
                      Save Changes
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="gap-1 text-xs"
                      disabled={isSavingResume}
                      onClick={() => {
                        setIsEditingResume(false);
                        setResumeDraft(app.resume || "");
                      }}
                    >
                      <RotateCcw className="size-3.5" /> Cancel
                    </Button>
                  </div>
                )}
              </div>

              {isEditingResume ? (
                <div className="space-y-2">
                  <Textarea
                    rows={12}
                    value={resumeDraft}
                    onChange={(e) => setResumeDraft(e.target.value)}
                    placeholder="Paste or edit tailored Markdown resume content here..."
                    className="bg-background font-mono text-xs leading-relaxed resize-none scroll-thin"
                  />
                  <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                    <CheckCircle2 className="size-3 text-success shrink-0" />
                    Edits are saved to your application's resume snapshot.
                  </p>
                </div>
              ) : app.resume ? (
                <div className="max-h-80 overflow-auto rounded-md border border-border bg-background p-4 scroll-thin select-text">
                  <MarkdownViewer content={app.resume} />
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-border p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-2.5">
                    No resume snapshot found for this application.
                  </p>
                  <Button
                    size="sm"
                    variant="subtle"
                    className="gap-1.5 text-xs"
                    onClick={() => {
                      setIsEditingResume(true);
                      setResumeDraft("");
                    }}
                  >
                    <FilePlus className="size-3.5" /> Add / Paste Resume Snapshot
                  </Button>
                </div>
              )}
            </section>
          </div>
        </SheetContent>
      </Sheet>

      {/* Dedicated Full Modal for Viewing & Editing the Submitted Resume Snapshot (CUJ-5, FR-04) */}
      <Dialog
        open={showResumeModal}
        onOpenChange={(open) => {
          setShowResumeModal(open);
          if (!open) {
            setIsEditingResume(false);
            setResumeDraft(app.resume || "");
          }
        }}
      >
        <DialogContent className="max-h-[85vh] sm:max-w-2xl flex flex-col p-6">
          <DialogHeader className="border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <DialogTitle className="text-base font-semibold">
                Resume Snapshot — {app.company}
              </DialogTitle>
              <Badge variant="success" className="gap-1 px-1.5 py-0 text-[10px]">
                <CheckCircle2 className="size-3" /> Tailored Snapshot
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {app.role} · Applied via {app.source}
            </p>
          </DialogHeader>

          <div className="flex items-center gap-2 pt-2">
            {!isEditingResume ? (
              <>
                <Button
                  size="sm"
                  variant="subtle"
                  className="gap-1.5 text-xs"
                  onClick={() => {
                    setIsEditingResume(true);
                    setResumeDraft(app.resume || "");
                  }}
                >
                  <Edit3 className="size-3.5" /> Edit Snapshot
                </Button>
                <Button size="sm" variant="subtle" className="gap-1.5 text-xs" onClick={handleCopyResume}>
                  <Copy className="size-3.5" /> Copy Markdown
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  variant="default"
                  className="gap-1.5 text-xs"
                  disabled={isSavingResume}
                  onClick={handleSaveResume}
                >
                  {isSavingResume ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <Save className="size-3.5" />
                  )}
                  Save Changes
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1.5 text-xs"
                  disabled={isSavingResume}
                  onClick={() => {
                    setIsEditingResume(false);
                    setResumeDraft(app.resume || "");
                  }}
                >
                  <RotateCcw className="size-3.5" /> Cancel
                </Button>
              </>
            )}
          </div>

          {isEditingResume ? (
            <div className="mt-2 flex-1 flex flex-col min-h-0 space-y-2">
              <Textarea
                rows={16}
                value={resumeDraft}
                onChange={(e) => setResumeDraft(e.target.value)}
                placeholder="Edit your tailored Markdown resume snapshot here..."
                className="flex-1 min-h-[300px] bg-background font-mono text-xs leading-relaxed resize-none scroll-thin"
              />
              <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1">
                <span>Markdown ATS snapshot · Linked to {app.company}</span>
                <span>{resumeDraft.length} characters</span>
              </div>
            </div>
          ) : app.resume ? (
            <div className="mt-2 flex-1 overflow-auto rounded-lg border border-border bg-background p-5 scroll-thin select-text">
              <MarkdownViewer content={app.resume} />
            </div>
          ) : (
            <div className="mt-4 flex-1 flex flex-col items-center justify-center rounded-lg border border-dashed border-border p-8 text-center">
              <p className="text-sm font-medium mb-1">No resume snapshot available</p>
              <p className="text-xs text-muted-foreground max-w-sm mb-4">
                This application does not have a saved resume snapshot yet. You can paste or write one now.
              </p>
              <Button
                size="sm"
                variant="subtle"
                className="gap-1.5 text-xs"
                onClick={() => {
                  setIsEditingResume(true);
                  setResumeDraft("");
                }}
              >
                <FilePlus className="size-3.5" /> Add / Paste Resume Snapshot
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
