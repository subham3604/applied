import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

type Theme = "light" | "dark";

function getPreferredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem("applied-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const preferred = getPreferredTheme();
    setTheme(preferred);
    document.documentElement.classList.toggle("dark", preferred === "dark");
    document.documentElement.style.colorScheme = preferred;
    setReady(true);
  }, []);

  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    document.documentElement.style.colorScheme = next;
    window.localStorage.setItem("applied-theme", next);
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8 rounded-full border border-border bg-surface text-muted-foreground shadow-none hover:bg-elevated hover:text-foreground"
      onClick={toggleTheme}
      aria-label={ready && theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={ready && theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {ready && theme === "dark" ? <Sun /> : <Moon />}
    </Button>
  );
}