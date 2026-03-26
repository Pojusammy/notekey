"use client";

import { useEffect } from "react";
import { Navbar } from "@/components/layout/navbar";
import { useHistoryStore } from "@/stores/use-history-store";
import { api } from "@/utils/api";

export default function HistoryPage() {
  const { sessions, isLoading, setSessions, removeSession, setLoading } =
    useHistoryStore();

  useEffect(() => {
    setLoading(true);
    api
      .getHistory()
      .then((data) => setSessions(data.map((d) => ({ ...d, userId: "" }))))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [setSessions, setLoading]);

  const handleDelete = async (id: string) => {
    try {
      await api.deleteSession(id);
      removeSession(id);
    } catch {}
  };

  return (
    <>
      <Navbar />
      <div className="relative z-10 mx-auto max-w-[760px] px-6 pb-24 pt-14">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <h1 className="animate-fade-up font-serif text-[clamp(26px,4vw,36px)] tracking-[-0.02em]">
            History
          </h1>
          <span className="rounded-full border border-border-subtle bg-surface-2 px-3 py-1 font-mono text-[12px] text-text-muted">
            {sessions.length} session{sessions.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex flex-col gap-2.5">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="animate-fade-up h-[72px] rounded-[20px] border border-border-subtle bg-surface"
                style={{ animationDelay: `${i * 40}ms`, opacity: 0.5 }}
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!isLoading && sessions.length === 0 && (
          <div className="animate-fade-up py-20 text-center">
            <span className="block text-[40px] opacity-50">🎼</span>
            <h3 className="mt-4 font-serif text-[20px] text-text-secondary">
              No sessions yet
            </h3>
            <p className="mt-2 text-[13px] text-text-muted">
              Use the Note Detector or Recording Analyzer to get started.
            </p>
          </div>
        )}

        {/* Session list */}
        {!isLoading && sessions.length > 0 && (
          <div className="flex flex-col gap-2.5">
            {sessions.map((session, i) => {
              const time = new Date(session.createdAt).toLocaleString("en-GB", {
                day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
              });
              return (
                <div
                  key={session.id}
                  className="animate-fade-up group flex items-center gap-4 rounded-[20px] border border-border-subtle bg-surface px-[22px] py-[18px] transition-all hover:translate-x-0.5 hover:border-border-strong hover:bg-surface-2"
                  style={{ animationDelay: `${i * 40}ms` }}
                >
                  {/* Type badge */}
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-lime/20 bg-lime-dim text-[16px]">
                    🎵
                  </div>

                  {/* Info */}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-medium">{session.title}</p>
                    <p className="text-[12px] text-text-secondary">{time}</p>
                  </div>

                  {/* Delete */}
                  <button
                    onClick={() => handleDelete(session.id)}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[16px] text-text-muted opacity-0 transition-all group-hover:opacity-100 hover:bg-danger/10 hover:text-danger"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
