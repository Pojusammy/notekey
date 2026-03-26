"use client";

import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { KeySelectorPill } from "@/components/shared/key-selector";

const NAV_ITEMS = [
  { href: "/", label: "Note Detector" },
  { href: "/analyzer", label: "Recording Analyzer" },
  { href: "/history", label: "History" },
];

const MOBILE_ITEMS = [
  { href: "/", label: "Detect", icon: "🎤" },
  { href: "/analyzer", label: "Analyze", icon: "🎵" },
  { href: "/history", label: "History", icon: "📋" },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <>
      {/* Desktop nav */}
      <nav className="sticky top-0 z-[100] flex h-[60px] items-center justify-between border-b border-border-subtle bg-canvas/85 px-8 backdrop-blur-[16px] backdrop-saturate-[1.8]">
        {/* Logo */}
        <a href="/" className="flex items-center gap-2.5">
          <div className="flex h-[30px] w-[30px] items-center justify-center rounded-lg bg-lime font-mono text-[13px] font-bold tracking-[-0.02em] text-canvas">
            nk
          </div>
          <span className="font-serif text-[18px] tracking-[-0.01em] text-text-primary">
            NoteKey
          </span>
        </a>

        {/* Pill tabs */}
        <div className="hidden items-center gap-1 rounded-xl border border-border-subtle bg-surface p-1 sm:flex">
          {NAV_ITEMS.map(({ href, label }) => (
            <button
              key={href}
              onClick={() => router.push(href)}
              className={cn(
                "rounded-lg px-4 py-1.5 text-[13px] font-medium tracking-[0.01em] transition-all",
                pathname === href
                  ? "bg-surface-3 text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.4),0_0_0_1px_rgba(255,255,255,0.04)]"
                  : "text-text-secondary hover:text-text-primary"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Key pill */}
        <KeySelectorPill />
      </nav>

      {/* Mobile bottom tabs */}
      <div className="fixed bottom-0 left-0 right-0 z-[100] flex gap-1 border-t border-border-subtle bg-canvas/95 px-4 pb-[calc(8px+env(safe-area-inset-bottom))] pt-2 backdrop-blur-[16px] sm:hidden">
        {MOBILE_ITEMS.map(({ href, label, icon }) => (
          <button
            key={href}
            onClick={() => router.push(href)}
            className={cn(
              "flex flex-1 flex-col items-center gap-1 rounded-lg py-2 text-[10px] transition-colors",
              pathname === href ? "text-lime" : "text-text-muted"
            )}
          >
            <span className="text-[20px]">{icon}</span>
            {label}
          </button>
        ))}
      </div>
    </>
  );
}
