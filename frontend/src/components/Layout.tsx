import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, FileText, Inbox, LayoutDashboard, Moon, NotebookText, Sun, Upload } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { api, ApiError } from "../lib/api";

const NAV = [
  { to: "/", label: "Resumen", icon: LayoutDashboard, end: true },
  { to: "/facturas", label: "Facturas", icon: FileText, end: false },
  { to: "/revision", label: "Revisión", icon: Inbox, end: false },
  { to: "/reportes", label: "Reportes", icon: NotebookText, end: false },
];

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(() => {
    try {
      return (localStorage.getItem("theme") as "light" | "dark" | null) ?? null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      if (theme) localStorage.setItem("theme", theme);
    } catch {
      /* storage unavailable: theme still works for this visit */
    }
  }, [theme]);
  const isDark =
    theme === "dark" || (theme === null && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return { isDark, toggle: () => setTheme(isDark ? "light" : "dark") };
}

function UploadButton() {
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: (result) => {
      queryClient.invalidateQueries();
      setMessage(result.message);
      navigate(`/facturas/${result.invoice_id}`);
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : "No se pudo subir."),
  });
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 6000);
    return () => clearTimeout(timer);
  }, [message]);

  return (
    <>
      <input
        ref={input}
        type="file"
        accept="application/pdf,image/png,image/jpeg"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate(file);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={upload.isPending}
        className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-ink shadow-sm hover:opacity-90 disabled:opacity-60"
      >
        <Upload className="size-4" aria-hidden />
        <span className="hidden sm:inline">{upload.isPending ? "Subiendo…" : "Subir factura"}</span>
      </button>
      {message && (
        <div
          role="status"
          className="fixed right-4 bottom-4 z-50 max-w-sm rounded-lg bg-surface px-4 py-3 text-sm shadow-lg ring-1 ring-line"
        >
          {message}
        </div>
      )}
    </>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { isDark, toggle } = useTheme();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
          <div className="flex items-center gap-2 font-semibold">
            <Bot className="size-5 text-accent" aria-hidden />
            <span className="hidden md:inline">Invoice Ops Agent</span>
          </div>
          <nav className="ml-2 flex flex-1 gap-1 overflow-x-auto">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm whitespace-nowrap ${
                    isActive ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2"
                  }`
                }
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>
          <button
            type="button"
            onClick={toggle}
            aria-label={isDark ? "Usar tema claro" : "Usar tema oscuro"}
            className="rounded-lg p-2 text-ink-2 hover:bg-surface-2"
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <UploadButton />
        </div>
      </header>
      <div className="border-b border-line bg-[var(--warning-wash)] px-4 py-1.5 text-center text-xs text-ink-2">
        Demo con datos 100 % sintéticos (facturas ficticias marcadas como "sin validez tributaria").
        No subas documentos reales.
      </div>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
