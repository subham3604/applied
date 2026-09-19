import { useState } from "react";
import { createFileRoute, useRouter } from "@tanstack/react-router";
import {
  Sparkles,
  ShieldCheck,
  Download,
  AlertTriangle,
  MapPin,
  Briefcase,
  Loader2,
  CheckCircle2,
  Globe,
} from "lucide-react";
import { TopNav } from "@/components/relay/TopNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Toaster } from "@/components/ui/sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { SAMPLE_JD } from "@/lib/relay-data";
import { parseJD, updateResume, type ParseJDResponse } from "@/lib/api";

export const Route = createFileRoute("/new-drop")({
  head: () => ({
    meta: [
      { title: "New Drop — Applied" },
      {
        name: "description",
        content:
          "Paste a raw job description, extract company, role and tech stack, and generate a resume snapshot grounded in your Master Vault.",
      },
      { property: "og:title", content: "New Drop — Applied" },
      {
        property: "og:description",
        content: "Manual ingestion and AI tailoring for job applications.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: NewDrop,
});

const DEFAULT_RESUME_PLACEHOLDER = `# Grounded Resume Snapshot
Tailored ATS Markdown resume will appear here once job description is parsed.
`;

export function NewDrop() {
  const router = useRouter();

  const [jd, setJd] = useState("");
  const [platform, setPlatform] = useState("Direct");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [parsedData, setParsedData] = useState<ParseJDResponse | null>(null);
  const [resume, setResume] = useState(DEFAULT_RESUME_PLACEHOLDER);
  const [edited, setEdited] = useState(false);

  async function handleParse() {
    const rawText = jd.trim() || SAMPLE_JD;
    if (!jd.trim()) setJd(SAMPLE_JD);

    setLoading(true);
    try {
      const res = await parseJD(rawText, platform);
      if (!res.success) {
        toast.error(res.error || "Failed to extract job description.");
        return;
      }

      setApplicationId(res.application_id || null);
      setParsedData(res);
      setResume(res.resume || DEFAULT_RESUME_PLACEHOLDER);
      setEdited(false);

      if (res.guard_passed) {
        toast.success(
          `Parsed job details for ${res.company || "application"}`,
        );
      } else {
        toast.info("Tailored resume generated for this role.");
      }
    } catch (err: any) {
      console.error("Parse error:", err);
      toast.error(err.message || "Failed to connect to server.");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirmAndSave() {
    if (!applicationId) {
      toast.error("Please parse a job description first before confirming.");
      return;
    }

    setSaving(true);
    try {
      if (edited && resume) {
        await updateResume(applicationId, resume);
      }
      toast.success(
        `Application saved to pipeline for ${parsedData?.company || "company"}!`,
      );
      router.navigate({ to: "/" });
    } catch (err: any) {
      console.error("Save error:", err);
      toast.error(err.message || "Failed to save resume snapshot.");
    } finally {
      setSaving(false);
    }
  }

  function handleExportMarkdown() {
    if (!resume || resume === DEFAULT_RESUME_PLACEHOLDER) {
      toast.error("No tailored resume to export yet.");
      return;
    }
    const blob = new Blob([resume], { type: "text/markdown;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const company = parsedData?.company?.toLowerCase().replace(/\s+/g, "_") || "tailored";
    link.setAttribute("download", `${company}_resume.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 2500);
    toast.success("Markdown exported successfully");
  }

  return (
    <div className="min-h-screen">
      <TopNav />

      <main className="mx-auto grid max-w-[1600px] gap-4 px-4 py-5 sm:px-6 lg:grid-cols-2">
        {/* Left: JD drop */}
        <section className="panel flex flex-col p-4">
          <header className="flex flex-wrap items-center gap-2">
            <h1 className="text-sm font-semibold">Job Description Drop</h1>
            <Badge variant="muted" className="ml-auto px-1.5 py-0 text-[10px]">
              Manual Ingestion
            </Badge>
          </header>

          <div className="mt-3 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Source Platform:</span>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger className="h-8 w-36 bg-background text-xs">
                <SelectValue placeholder="Platform" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Direct">Direct Portal</SelectItem>
                <SelectItem value="Naukri">Naukri</SelectItem>
                <SelectItem value="LinkedIn">LinkedIn</SelectItem>
                <SelectItem value="Wellfound">Wellfound</SelectItem>
                <SelectItem value="Indeed">Indeed</SelectItem>
              </SelectContent>
            </Select>

            <Button
              variant="subtle"
              size="sm"
              onClick={() => setJd(SAMPLE_JD)}
              className="ml-auto h-8 text-[11px]"
            >
              Load Sample Swiggy JD
            </Button>
          </div>

          <Textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            placeholder="Paste raw job description text from LinkedIn, Naukri, or career portal..."
            className="mt-3 min-h-64 resize-none bg-background font-mono text-xs leading-relaxed"
          />

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              variant="ai"
              disabled={loading}
              onClick={handleParse}
              className="gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Extracting &amp; Tailoring...
                </>
              ) : (
                <>
                  <Sparkles className="size-4" />
                  Parse &amp; Tailor Resume
                </>
              )}
            </Button>
            <span className="text-[11px] text-muted-foreground">
              {jd.trim().length} chars staged
            </span>
          </div>

          <div className="mt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Extracted Metadata
            </h2>
            {parsedData ? (
              <div className="mt-2 rounded-lg border border-border bg-background p-3">
                <div className="flex items-start gap-2.5">
                  <span className="grid size-8 place-items-center rounded-md border border-border bg-elevated text-xs font-semibold uppercase">
                    {parsedData.company ? parsedData.company.slice(0, 1) : "?"}
                  </span>
                  <div>
                    <p className="text-sm font-semibold">{parsedData.company}</p>
                    <p className="text-xs text-muted-foreground">{parsedData.role}</p>
                  </div>
                  <Badge variant="info" className="ml-auto px-1.5 py-0 text-[10px]">
                    {parsedData.source || platform}
                  </Badge>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge variant="muted" className="gap-1 px-1.5 py-0 text-[10px]">
                    <MapPin className="size-3" /> {parsedData.location || "Location not specified"}
                  </Badge>
                  {parsedData.guard_passed && (
                    <Badge variant="success" className="gap-1 px-1.5 py-0 text-[10px]">
                      <CheckCircle2 className="size-3" /> Anti-Hallucination Guard Passed
                    </Badge>
                  )}
                </div>

                <div className="mt-3">
                  <p className="mb-1.5 text-[11px] text-muted-foreground">Detected Tech Stack</p>
                  <div className="flex flex-wrap gap-1.5">
                    {(parsedData.stack || []).map((t) => (
                      <span
                        key={t}
                        className="rounded-full border border-ai/40 bg-ai/10 px-2 py-0.5 font-mono text-[10px] text-ai"
                      >
                        {t}
                      </span>
                    ))}
                    {(parsedData.stack || []).length === 0 && (
                      <span className="text-[11px] text-muted-foreground">
                        No specific tech stack extracted
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-2 rounded-lg border border-dashed border-border px-3 py-6 text-center text-[11px] text-muted-foreground">
                Metadata populates after AI extraction.
              </p>
            )}
          </div>
        </section>

        {/* Right: resume snapshot */}
        <section className="panel flex flex-col p-4">
          <header className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">Grounded Resume Snapshot</h2>
            <Badge variant="success" className="gap-1 px-1.5 py-0 text-[10px]">
              <ShieldCheck className="size-3" /> Verified Profile
            </Badge>
            <Button
              size="sm"
              variant="subtle"
              className="ml-auto"
              onClick={handleExportMarkdown}
            >
              <Download /> Export Markdown
            </Button>
          </header>

          {edited && (
            <div className="mt-3 flex items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-[11px] text-warning">
              <AlertTriangle className="size-3.5" />
              Manually edited from AI-generated snapshot (will save with is_user_edited=true)
            </div>
          )}

          <Textarea
            value={resume}
            onChange={(e) => {
              setResume(e.target.value);
              setEdited(true);
            }}
            placeholder="AI tailored resume will appear here..."
            className="mt-3 min-h-[26rem] flex-1 resize-none bg-background font-mono text-xs leading-relaxed scroll-thin"
          />

          <div className="sticky bottom-0 mt-3 bg-surface pt-1">
            <Button
              className="w-full"
              disabled={!applicationId || saving}
              onClick={handleConfirmAndSave}
            >
              {saving ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving Snapshot to Pipeline...
                </>
              ) : (
                "Confirm & Save to Pipeline"
              )}
            </Button>
          </div>
        </section>
      </main>

      <Toaster />
    </div>
  );
}
