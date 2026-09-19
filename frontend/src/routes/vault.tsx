import { useState, useEffect, useMemo, useCallback } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  Database,
  Plus,
  Search,
  Sparkles,
  Tag,
  Trash2,
  Edit3,
  CheckCircle2,
  Briefcase,
  FolderGit2,
  Cpu,
  GraduationCap,
  Loader2,
  X,
  AlertTriangle,
} from "lucide-react";
import { TopNav } from "@/components/relay/TopNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  fetchVaultBullets,
  createVaultBullet,
  updateVaultBullet,
  deleteVaultBullet,
  type VaultBullet,
  type VaultCategory,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/vault")({
  head: () => ({
    meta: [
      { title: "Master Experience Vault — Applied" },
      {
        name: "description",
        content:
          "Manage verified career claims, experience achievements, and technical skills for smart resume tailoring.",
      },
      { property: "og:title", content: "Master Experience Vault — Applied" },
      {
        property: "og:description",
        content:
          "Curate your single source of truth for grounded career claims.",
      },
    ],
  }),
  component: VaultDashboard,
});

const CATEGORIES: { id: "ALL" | VaultCategory; label: string; icon: typeof Briefcase; color: string }[] = [
  { id: "ALL", label: "All Items", icon: Database, color: "text-foreground" },
  { id: "WORK_EXPERIENCE", label: "Work Experience", icon: Briefcase, color: "text-info" },
  { id: "PROJECT", label: "Projects", icon: FolderGit2, color: "text-success" },
  { id: "SKILL", label: "Skills", icon: Cpu, color: "text-ai" },
  { id: "EDUCATION", label: "Education", icon: GraduationCap, color: "text-warning" },
];

export function VaultDashboard() {
  const [bullets, setBullets] = useState<VaultBullet[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCategory, setActiveCategory] = useState<"ALL" | VaultCategory>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Modal states
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingBullet, setEditingBullet] = useState<VaultBullet | null>(null);
  const [deletingBullet, setDeletingBullet] = useState<VaultBullet | null>(null);
  const [saving, setSaving] = useState(false);

  // Form states
  const [formCategory, setFormCategory] = useState<VaultCategory>("WORK_EXPERIENCE");
  const [formTitle, setFormTitle] = useState("");
  const [formText, setFormText] = useState("");
  const [formTags, setFormTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");

  const loadBullets = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchVaultBullets();
      setBullets(data);
    } catch (err: any) {
      console.error("Failed to load vault bullets:", err);
      toast.error(err.message || "Failed to load master experience vault.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBullets();
  }, [loadBullets]);

  // Counts by category
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {
      ALL: bullets.length,
      WORK_EXPERIENCE: 0,
      PROJECT: 0,
      SKILL: 0,
      EDUCATION: 0,
    };
    for (const b of bullets) {
      if (counts[b.category] !== undefined) {
        counts[b.category]++;
      }
    }
    return counts;
  }, [bullets]);

  // Filtered bullets
  const filteredBullets = useMemo(() => {
    return bullets.filter((b) => {
      const matchCat = activeCategory === "ALL" || b.category === activeCategory;
      if (!matchCat) return false;

      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase().trim();
      const inTitle = b.title.toLowerCase().includes(q);
      const inText = b.bullet_point.toLowerCase().includes(q);
      const inTags = (b.tech_tags || []).some((t) => t.toLowerCase().includes(q));
      return inTitle || inText || inTags;
    });
  }, [bullets, activeCategory, searchQuery]);

  function handleOpenCreate() {
    setEditingBullet(null);
    setFormCategory(activeCategory === "ALL" ? "WORK_EXPERIENCE" : activeCategory);
    setFormTitle("");
    setFormText("");
    setFormTags([]);
    setTagInput("");
    setIsModalOpen(true);
  }

  function handleOpenEdit(b: VaultBullet) {
    setEditingBullet(b);
    setFormCategory(b.category);
    setFormTitle(b.title);
    setFormText(b.bullet_point);
    setFormTags([...b.tech_tags]);
    setTagInput("");
    setIsModalOpen(true);
  }

  function handleAddTag() {
    const clean = tagInput.trim().replace(/,/g, "");
    if (clean && !formTags.includes(clean)) {
      setFormTags([...formTags, clean]);
      setTagInput("");
    }
  }

  function handleRemoveTag(tagToRemove: string) {
    setFormTags(formTags.filter((t) => t !== tagToRemove));
  }

  async function handleSave() {
    if (!formTitle.trim()) {
      toast.error("Please provide a title or project/company name.");
      return;
    }
    if (!formText.trim()) {
      toast.error("Please enter bullet point text.");
      return;
    }

    setSaving(true);
    try {
      if (editingBullet) {
        await updateVaultBullet(editingBullet.id, {
          category: formCategory,
          title: formTitle.trim(),
          bullet_point: formText.trim(),
          tech_tags: formTags,
        });
        toast.success("Experience bullet updated successfully.");
      } else {
        await createVaultBullet({
          category: formCategory,
          title: formTitle.trim(),
          bullet_point: formText.trim(),
          tech_tags: formTags,
        });
        toast.success("Experience bullet added to your vault.");
      }
      setIsModalOpen(false);
      await loadBullets();
    } catch (err: any) {
      console.error("Save error:", err);
      toast.error(err.message || "Failed to save bullet to vault.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!deletingBullet) return;
    try {
      await deleteVaultBullet(deletingBullet.id);
      toast.success("Deleted bullet from vault.");
      setDeletingBullet(null);
      await loadBullets();
    } catch (err: any) {
      console.error("Delete error:", err);
      toast.error(err.message || "Failed to delete bullet.");
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopNav />

      <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">
        {/* Header section */}
        <div className="flex flex-col justify-between gap-4 border-b border-border pb-6 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg bg-ai/15 text-ai shadow-sm">
                <Database className="size-4" />
              </span>
              <h1 className="text-xl font-bold tracking-tight">Master Experience Vault</h1>
              <Badge variant="outline" className="ml-2 text-[11px] font-medium text-ai border-ai/30 bg-ai/5">
                AI-Indexed
              </Badge>
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground max-w-2xl leading-relaxed">
              Your ground-truth repository of verified career achievements, metrics, and technology skills.
              Automatically matched and tailored to relevant job descriptions when generating resumes.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Button
              onClick={handleOpenCreate}
              className="h-9 gap-1.5 rounded-lg bg-primary text-primary-foreground px-3 text-xs font-semibold shadow-sm hover:brightness-90 dark:hover:brightness-110 active:scale-[0.98] transition-all cursor-pointer"
            >
              <Plus className="size-3.5" />
              Add Bullet
            </Button>
          </div>
        </div>

        {/* Toolbar & Filter pills */}
        <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          {/* Category Tabs */}
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-surface/80 p-1.5">
            {CATEGORIES.map((cat) => {
              const Icon = cat.icon;
              const isSelected = activeCategory === cat.id;
              const count = categoryCounts[cat.id] || 0;
              return (
                <button
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.id)}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                    isSelected
                      ? "bg-elevated text-foreground shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:text-foreground hover:bg-surface/50"
                  )}
                >
                  <Icon className={cn("size-3.5", cat.color)} />
                  <span>{cat.label}</span>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.2 text-[10px] tabular-nums",
                      isSelected ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground"
                    )}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Search box */}
          <div className="relative w-full lg:w-80">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by keyword, tag, or title..."
              className="h-9 pl-9 pr-8 text-xs bg-surface border-border focus-visible:ring-1 focus-visible:ring-primary"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Vault Grid Content */}
        <div className="mt-6">
          {loading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div
                  key={i}
                  className="h-44 animate-pulse rounded-xl border border-border/70 bg-surface/40 p-4"
                />
              ))}
            </div>
          ) : filteredBullets.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-16 text-center">
              <div className="grid size-12 place-items-center rounded-full bg-surface text-muted-foreground">
                <Database className="size-6" />
              </div>
              <h3 className="mt-4 text-sm font-semibold text-foreground">No experience bullets found</h3>
              <p className="mt-1 text-xs text-muted-foreground max-w-sm">
                {searchQuery
                  ? `No vault entries matched "${searchQuery}". Try a different keyword.`
                  : "Start adding verified career claims to power automated resume tailoring."}
              </p>
              <Button
                onClick={handleOpenCreate}
                variant="outline"
                className="mt-5 h-8 text-xs border-border bg-surface"
              >
                <Plus className="mr-1.5 size-3.5" /> Add Your First Bullet
              </Button>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredBullets.map((bullet) => {
                const isWork = bullet.category === "WORK_EXPERIENCE";
                const isProj = bullet.category === "PROJECT";
                const isSkill = bullet.category === "SKILL";

                return (
                  <article
                    key={bullet.id}
                    onClick={() => handleOpenEdit(bullet)}
                    className="group relative flex h-64 cursor-pointer flex-col justify-between rounded-xl border border-border/70 bg-surface/60 p-4 shadow-sm transition-all hover:border-primary/40 hover:bg-surface hover:shadow-md"
                  >
                    <div className="flex flex-1 flex-col overflow-hidden">
                      {/* Card Header */}
                      <div className="flex h-7 shrink-0 items-center justify-between gap-2">
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px] font-medium tracking-wide uppercase px-2 py-0.5",
                            isWork && "border-info/30 bg-info/10 text-info",
                            isProj && "border-success/30 bg-success/10 text-success",
                            isSkill && "border-ai/30 bg-ai/10 text-ai",
                            bullet.category === "EDUCATION" && "border-warning/30 bg-warning/10 text-warning"
                          )}
                        >
                          {bullet.category.replace("_", " ")}
                        </Badge>

                        {/* Action buttons */}
                        <div className="flex items-center gap-1 opacity-80 transition-opacity group-hover:opacity-100">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleOpenEdit(bullet);
                            }}
                            title="Edit bullet"
                            className="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                          >
                            <Edit3 className="size-3.5" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeletingBullet(bullet);
                            }}
                            title="Delete bullet"
                            className="grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-danger/15 hover:text-danger"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Title */}
                      <h3
                        className="mt-2.5 truncate text-sm font-semibold tracking-tight text-foreground shrink-0"
                        title={bullet.title}
                      >
                        {bullet.title}
                      </h3>

                      {/* Bullet Text */}
                      <div className="mt-2 flex-1 overflow-hidden">
                        <p
                          className="text-xs leading-relaxed text-foreground/90 line-clamp-4"
                          title={bullet.bullet_point}
                        >
                          {bullet.bullet_point}
                        </p>
                      </div>
                    </div>

                    {/* Footer Tags: strictly single line, aligned at bottom */}
                    <div className="mt-3 flex h-7 shrink-0 items-center justify-between border-t border-border/40 pt-2.5 overflow-hidden">
                      {bullet.tech_tags && bullet.tech_tags.length > 0 ? (
                        <div className="flex items-center gap-1 overflow-hidden">
                          {bullet.tech_tags.slice(0, 3).map((tag, idx) => (
                            <span
                              key={idx}
                              className="inline-flex shrink-0 items-center rounded-md bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                            >
                              {tag}
                            </span>
                          ))}
                          {bullet.tech_tags.length > 3 && (
                            <span className="inline-flex shrink-0 items-center rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                              +{bullet.tech_tags.length - 3}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="font-mono text-[10px] italic text-muted-foreground/60">
                          No tags
                        </span>
                      )}

                      <span className="ml-2 shrink-0 font-mono text-[10px] text-muted-foreground/40">
                        {bullet.tech_tags?.length || 0} tag{(bullet.tech_tags?.length || 0) === 1 ? "" : "s"}
                      </span>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      </main>

      {/* Add / Edit Dialog Modal */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-lg bg-surface border-border">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-foreground flex items-center gap-2">
              <Sparkles className="size-4 text-ai" />
              {editingBullet ? "Edit Experience Bullet" : "Add Experience Bullet"}
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              {editingBullet
                ? "Update your achievement or metrics. Changes are automatically saved to your career vault."
                : "Add a metric-rich career achievement or skill to match against incoming job descriptions."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Category Select */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-foreground">Category</label>
              <Select
                value={formCategory}
                onValueChange={(val: VaultCategory) => setFormCategory(val)}
              >
                <SelectTrigger className="h-9 text-xs bg-background border-border">
                  <SelectValue placeholder="Select Category" />
                </SelectTrigger>
                <SelectContent className="bg-surface border-border">
                  <SelectItem value="WORK_EXPERIENCE" className="text-xs">
                    Work Experience
                  </SelectItem>
                  <SelectItem value="PROJECT" className="text-xs">
                    Project
                  </SelectItem>
                  <SelectItem value="SKILL" className="text-xs">
                    Skill
                  </SelectItem>
                  <SelectItem value="EDUCATION" className="text-xs">
                    Education
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Title Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-foreground">
                Title / Context <span className="text-danger">*</span>
              </label>
              <Input
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
                placeholder="e.g., SDE-1 Payments Platform, Autonomous Career Pipeline"
                className="h-9 text-xs bg-background border-border"
              />
            </div>

            {/* Bullet Textarea */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-foreground">
                  Bullet Point Text <span className="text-danger">*</span>
                </label>
                <span className="text-[10px] text-muted-foreground tabular-nums">
                  {formText.length} chars
                </span>
              </div>
              <Textarea
                rows={4}
                value={formText}
                onChange={(e) => setFormText(e.target.value)}
                placeholder="Include specific metrics, business impact, and technologies used (e.g. Cut p99 checkout latency 38% by rework of Redis cache keys...)"
                className="text-xs bg-background border-border leading-relaxed"
              />
            </div>

            {/* Tech Tags Chip Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-foreground">
                Technology Tags
              </label>
              <div className="flex gap-2">
                <Input
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      handleAddTag();
                    }
                  }}
                  placeholder="Type tag (e.g., FastAPI) and press Enter"
                  className="h-8 text-xs bg-background border-border"
                />
                <Button
                  type="button"
                  onClick={handleAddTag}
                  variant="outline"
                  className="h-8 px-2.5 text-xs border-border shrink-0"
                >
                  Add Tag
                </Button>
              </div>

              {formTags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1.5">
                  {formTags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 rounded-md bg-elevated px-2 py-0.5 text-xs text-foreground font-mono"
                    >
                      {tag}
                      <button
                        type="button"
                        onClick={() => handleRemoveTag(tag)}
                        className="text-muted-foreground hover:text-danger"
                      >
                        <X className="size-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsModalOpen(false)}
              className="h-9 text-xs border-border"
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className="h-9 gap-1.5 text-xs font-semibold bg-primary text-primary-foreground shadow-sm hover:brightness-90 dark:hover:brightness-110 active:scale-[0.98] transition-all cursor-pointer"
            >
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
              {editingBullet ? "Save Changes" : "Save Bullet"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deletingBullet} onOpenChange={(open) => !open && setDeletingBullet(null)}>
        <DialogContent className="sm:max-w-md bg-surface border-border">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-danger flex items-center gap-2">
              <AlertTriangle className="size-4" />
              Delete Vault Entry
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Are you sure you want to delete this bullet from your vault?
              This action cannot be undone. It will no longer be matched when tailoring resumes.
            </DialogDescription>
          </DialogHeader>

          {deletingBullet && (
            <div className="rounded-lg border border-border bg-background p-3 text-xs text-muted-foreground">
              <p className="font-semibold text-foreground">{deletingBullet.title}</p>
              <p className="mt-1 line-clamp-2">{deletingBullet.bullet_point}</p>
            </div>
          )}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeletingBullet(null)}
              className="h-9 text-xs border-border"
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleDeleteConfirm}
              className="h-9 text-xs font-semibold bg-danger text-danger-foreground hover:bg-danger/90"
            >
              Delete Bullet
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Toaster position="bottom-right" />
    </div>
  );
}
