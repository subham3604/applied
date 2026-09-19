import {
  parseISO,
  isValid,
  isToday,
  isYesterday,
  differenceInMinutes,
  differenceInHours,
  differenceInDays,
  format,
} from "date-fns";

/**
 * Parses an ISO date string or Date object safely.
 */
export function parseDateSafe(input?: string | Date | null): Date | null {
  if (!input) return null;
  if (input instanceof Date) return isValid(input) ? input : null;
  try {
    const parsed = parseISO(input);
    if (isValid(parsed)) return parsed;
    const fallback = new Date(input);
    return isValid(fallback) ? fallback : null;
  } catch {
    return null;
  }
}

/**
 * Formats the application applied date cleanly for Kanban cards and drawers.
 * Avoids raw ISO strings like "2026-09-17T21:32:16.332798+00:00".
 * Examples:
 *  - "Applied just now"
 *  - "Applied 14m ago"
 *  - "Applied 3h ago"
 *  - "Applied yesterday"
 *  - "Applied 4d ago"
 *  - "Applied Sep 12"
 */
export function formatApplied(rawDate?: string | null, rawTimestamp?: string | null): string {
  const candidate = rawTimestamp || rawDate;
  if (!candidate) return "Applied recently";

  // If already a human formatted string like "Applied 3d ago" and not an ISO timestamp
  if (
    typeof candidate === "string" &&
    candidate.startsWith("Applied ") &&
    !candidate.includes("T") &&
    !candidate.includes("+")
  ) {
    return candidate;
  }

  const date = parseDateSafe(candidate);
  if (!date) {
    // If it's already a non-ISO string, keep it clean
    if (typeof candidate === "string" && candidate.length < 30 && !candidate.includes("T")) {
      return candidate.startsWith("Applied") ? candidate : `Applied ${candidate}`;
    }
    return "Applied recently";
  }

  const now = new Date();
  const diffMins = differenceInMinutes(now, date);
  const diffHours = differenceInHours(now, date);
  const diffDays = differenceInDays(now, date);

  if (diffMins < 1) {
    return "Applied just now";
  }
  if (diffMins < 60) {
    return `Applied ${diffMins}m ago`;
  }
  if (diffHours < 24 && isToday(date)) {
    return `Applied ${diffHours}h ago`;
  }
  if (isYesterday(date)) {
    return `Applied yesterday`;
  }
  if (diffDays < 7 && diffDays >= 0) {
    return `Applied ${diffDays}d ago`;
  }

  const isCurrentYear = date.getFullYear() === now.getFullYear();
  return `Applied ${format(date, isCurrentYear ? "MMM d" : "MMM d, yyyy")}`;
}

/**
 * Returns a human-friendly full localized date & time for tooltips and headers.
 * Example: "Sep 18, 2026 at 3:02 AM"
 */
export function formatFullDateTime(input?: string | Date | null): string {
  const date = parseDateSafe(input);
  if (!date) return "";
  return format(date, "MMM d, yyyy 'at' h:mm a");
}

/**
 * Formats a timeline event date & time.
 * If exact timestamp is available, shows localized relative date + time.
 * Examples:
 *  - "Today, 3:02 AM"
 *  - "Yesterday, 9:15 PM"
 *  - "Sep 15 · 4:30 PM"
 */
export function formatTimelineDate(
  eventDate?: string,
  timestampStr?: string | null,
): { display: string; full: string } {
  const date = parseDateSafe(timestampStr || eventDate);
  if (!date) {
    return {
      display: eventDate || "Recent",
      full: eventDate || "",
    };
  }

  const full = format(date, "PPPPp"); // e.g. "Friday, September 18th, 2026 at 3:02 AM"

  if (isToday(date)) {
    return {
      display: `Today, ${format(date, "h:mm a")}`,
      full,
    };
  }

  if (isYesterday(date)) {
    return {
      display: `Yesterday, ${format(date, "h:mm a")}`,
      full,
    };
  }

  const now = new Date();
  const isCurrentYear = date.getFullYear() === now.getFullYear();
  return {
    display: `${format(date, isCurrentYear ? "MMM d" : "MMM d, yyyy")} · ${format(date, "h:mm a")}`,
    full,
  };
}
