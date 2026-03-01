"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { queryAPI } from "@/lib/api";
import type { QueryHistoryItem } from "@/types";
import { formatDateTime, getVerificationColor, getConfidenceColor, cn } from "@/lib/utils";
import toast from "react-hot-toast";

export default function HistoryPage() {
  const [queries, setQueries] = useState<QueryHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const LIMIT = 15;

  const fetchHistory = async (off: number) => {
    setLoading(true);
    try {
      const data = await queryAPI.history(LIMIT, off);
      setQueries(data.queries);
      setTotal(data.total);
      setOffset(off);
    } catch {
      toast.error("Failed to load history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchHistory(0); }, []);

  return (
    <div className="p-4 sm:p-5 lg:p-8 min-h-full">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">Query History</h1>
            <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">{total} queries total</p>
          </div>
          <Link
            href="/query"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-amber-600 transition-colors flex-shrink-0"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
            <span className="hidden sm:inline">New Query</span>
          </Link>
        </div>

        <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : queries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-4">
              <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-5xl">history</span>
              <p className="text-gray-400 dark:text-slate-500 text-sm mt-3">No queries yet</p>
              <Link href="/query" className="mt-3 text-sm text-primary hover:text-amber-500 font-medium">Ask your first question →</Link>
            </div>
          ) : (
            <div className="divide-y divide-gray-100 dark:divide-slate-800">
              {queries.map((q) => (
                <Link
                  key={q.query_id}
                  href={`/query?q=${encodeURIComponent(q.query_text)}`}
                  className="flex items-center gap-3 sm:gap-4 px-4 sm:px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors group"
                >
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="material-symbols-outlined text-primary text-[18px]">forum</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                      {q.query_text}
                    </p>
                    <p className="text-xs text-gray-400 dark:text-slate-600 mt-0.5">{formatDateTime(q.created_at)}</p>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded border font-medium", getVerificationColor(q.verification_status))}>
                      {q.verification_status === "VERIFIED" ? "Verified" :
                       q.verification_status === "PARTIALLY_VERIFIED" ? "Partial" : "Unverified"}
                    </span>
                    <span className={cn("text-xs font-medium capitalize hidden sm:inline", getConfidenceColor(q.confidence))}>
                      {q.confidence}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Pagination */}
        {total > LIMIT && (
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => fetchHistory(Math.max(0, offset - LIMIT))}
              disabled={offset === 0 || loading}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              <span className="material-symbols-outlined text-[16px]">chevron_left</span>
              Previous
            </button>
            <span className="text-xs text-gray-500 dark:text-slate-500">
              {offset + 1}–{Math.min(offset + LIMIT, total)} of {total}
            </span>
            <button
              onClick={() => fetchHistory(offset + LIMIT)}
              disabled={offset + LIMIT >= total || loading}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              Next
              <span className="material-symbols-outlined text-[16px]">chevron_right</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
