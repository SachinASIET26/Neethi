"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { queryAPI } from "@/lib/api";
import { useUIStore } from "@/store/ui";
import { useTranslations } from "@/lib/i18n";
import type { QueryHistoryItem } from "@/types";
import { formatDateTime, getVerificationColor, getConfidenceColor, cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import toast from "react-hot-toast";

interface CachedMessage {
  query: string;
  response: string;
  timestamp: string;
  verification_status?: string;
  confidence?: string;
}

function getCachedResponse(queryText: string): string | null {
  try {
    const stored = JSON.parse(localStorage.getItem("neethi-chat-history") || "[]") as CachedMessage[];
    const match = stored.find((item) => item.query === queryText);
    return match?.response ?? null;
  } catch {
    return null;
  }
}

export default function HistoryPage() {
  const router = useRouter();
  const { selectedLanguage } = useUIStore();
  const t = useTranslations(selectedLanguage);

  const [queries, setQueries] = useState<QueryHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewResponse, setPreviewResponse] = useState<string | null>(null);
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

  const handleToggleExpand = (q: QueryHistoryItem) => {
    if (expandedId === q.query_id) {
      setExpandedId(null);
      setPreviewResponse(null);
      return;
    }
    setExpandedId(q.query_id);
    const cached = getCachedResponse(q.query_text);
    setPreviewResponse(cached);
  };

  const handleRunAgain = (queryText: string) => {
    router.push(`/query?q=${encodeURIComponent(queryText)}`);
  };

  return (
    <div className="p-4 sm:p-5 lg:p-8 min-h-full">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">{t.queryHistory}</h1>
            <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
              {total} {t.queriesTotal}
            </p>
          </div>
          <Link
            href="/query"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-amber-600 transition-colors flex-shrink-0"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
            <span className="hidden sm:inline">{t.newQuery}</span>
          </Link>
        </div>

        {/* List */}
        <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : queries.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-4">
              <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-5xl">history</span>
              <p className="text-gray-400 dark:text-slate-500 text-sm mt-3">{t.noQueriesYet}</p>
              <Link href="/query" className="mt-3 text-sm text-primary hover:text-amber-500 font-medium">
                {t.askFirstQuestion}
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-gray-100 dark:divide-slate-800">
              {queries.map((q) => (
                <div key={q.query_id}>
                  {/* Row */}
                  <div
                    className="flex items-center gap-3 sm:gap-4 px-4 sm:px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors group cursor-pointer"
                    onClick={() => handleToggleExpand(q)}
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
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className={cn("text-[10px] px-2 py-0.5 rounded border font-medium", getVerificationColor(q.verification_status))}>
                        {q.verification_status === "VERIFIED" ? t.verified :
                         q.verification_status === "PARTIALLY_VERIFIED" ? t.partial : t.unverified}
                      </span>
                      <span className={cn("text-xs font-medium capitalize hidden sm:inline", getConfidenceColor(q.confidence))}>
                        {q.confidence}
                      </span>
                      <span className="material-symbols-outlined text-gray-400 dark:text-slate-500 text-[18px] transition-transform duration-200"
                        style={{ transform: expandedId === q.query_id ? "rotate(180deg)" : "rotate(0deg)" }}>
                        expand_more
                      </span>
                    </div>
                  </div>

                  {/* Expanded Preview */}
                  {expandedId === q.query_id && (
                    <div className="bg-gray-50 dark:bg-slate-900/50 border-t border-gray-100 dark:border-slate-800 px-4 sm:px-5 py-4 animate-fade-in">

                      {/* Query preview */}
                      <div className="mb-3">
                        <p className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">Query</p>
                        <p className="text-sm text-gray-800 dark:text-slate-200 leading-relaxed">
                          {q.query_text}
                        </p>
                      </div>

                      {/* Metadata badges */}
                      <div className="flex flex-wrap gap-2 mb-4">
                        <span className={cn("text-[10px] px-2 py-0.5 rounded border font-medium", getVerificationColor(q.verification_status))}>
                          {q.verification_status?.replace(/_/g, " ")}
                        </span>
                        <span className={cn("text-xs font-medium capitalize px-2 py-0.5 rounded border border-gray-200 dark:border-slate-700", getConfidenceColor(q.confidence))}>
                          {q.confidence} confidence
                        </span>
                        <span className="text-[10px] text-gray-400 dark:text-slate-500 px-2 py-0.5 rounded border border-gray-200 dark:border-slate-700">
                          {formatDateTime(q.created_at)}
                        </span>
                      </div>

                      {/* Response preview */}
                      <div className="mb-4">
                        <p className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                          {t.viewResponse}
                        </p>
                        {previewResponse ? (
                          <div className="bg-white dark:bg-[#0f172a] border border-gray-200 dark:border-slate-800 rounded-xl p-4 max-h-72 overflow-y-auto">
                            <div className="markdown-body text-sm text-gray-800 dark:text-slate-200 leading-relaxed">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{previewResponse}</ReactMarkdown>
                            </div>
                          </div>
                        ) : (
                          <div className="bg-white dark:bg-[#0f172a] border border-dashed border-gray-200 dark:border-slate-700 rounded-xl p-4 text-center">
                            <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-3xl block mb-1">history_toggle_off</span>
                            <p className="text-xs text-gray-400 dark:text-slate-500">{t.noResponseStored}</p>
                          </div>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleRunAgain(q.query_text)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-amber-600 transition-colors"
                        >
                          <span className="material-symbols-outlined text-[15px]">refresh</span>
                          {t.runAgain}
                        </button>
                        <button
                          onClick={() => { setExpandedId(null); setPreviewResponse(null); }}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-xs font-medium text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                        >
                          <span className="material-symbols-outlined text-[15px]">close</span>
                          Close
                        </button>
                      </div>
                    </div>
                  )}
                </div>
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
