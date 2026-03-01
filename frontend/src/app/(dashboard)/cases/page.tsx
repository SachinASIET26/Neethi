"use client";

import { useState } from "react";
import { casesAPI } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import type {
  CaseSearchRequest,
  CaseSearchResponse,
  CaseResult,
  CaseAnalysisRequest,
  CaseAnalysisResponse,
  IRACAnalysis,
} from "@/types";
import { getVerificationColor, getConfidenceColor, cn } from "@/lib/utils";
import toast from "react-hot-toast";

/* ─── Sub-components ─────────────────────────────────────────── */

function RelevanceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-gray-400 dark:bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 dark:text-slate-400 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  );
}

function CaseCard({ c, onSelect, selected }: { c: CaseResult; onSelect: () => void; selected: boolean }) {
  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full text-left p-4 rounded-xl border transition-all",
        selected
          ? "border-primary bg-primary/5"
          : "border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] hover:border-gray-300 dark:hover:border-slate-700"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900 dark:text-white leading-snug">{c.case_name}</p>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 font-mono">{c.citation}</p>
        </div>
        <span className="flex-shrink-0 text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 border border-gray-200 dark:border-slate-700">
          {c.court}
        </span>
      </div>

      <p className="text-xs text-gray-500 dark:text-slate-400 mt-2 line-clamp-2 leading-relaxed">
        {c.summary}
      </p>

      <div className="mt-3 space-y-1.5">
        <RelevanceBar score={c.relevance_score} />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 flex-wrap">
            {c.sections_cited.slice(0, 3).map((s) => (
              <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono">
                {s}
              </span>
            ))}
            {c.sections_cited.length > 3 && (
              <span className="text-[10px] text-gray-400 dark:text-slate-500">+{c.sections_cited.length - 3} more</span>
            )}
          </div>
          <span className="text-[10px] text-gray-400 dark:text-slate-500">{c.judgment_date}</span>
        </div>
      </div>
    </button>
  );
}

/* ─── Inline legal citation highlighter ──────────────────────── */

function Cite({ text }: { text: string }) {
  // Match patterns like CPC_1908 s.53, IPC s.302, BNS s.4, CrPC s.154_A
  const regex = /\b([A-Z][A-Z_\d]+)\s+s\.(\w+)\b/g;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  regex.lastIndex = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(
      <code
        key={m.index}
        className="text-[11px] mx-0.5 px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono whitespace-nowrap not-italic"
      >
        {m[0]}
      </code>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

/* ─── IRAC section structured content renderer ────────────────── */

type IRACKey = keyof IRACAnalysis;

function splitSentences(text: string): string[] {
  return text
    .split(/\.(?=\s+[A-Z(])/)
    .map((s, i, arr) => (i < arr.length - 1 ? s.trim() + "." : s.trim()))
    .filter((s) => s.length > 5);
}

function IRACContent({ content, sectionKey }: { content: string; sectionKey: IRACKey }) {
  // Strip embedded "APPLICABLE SECTIONS / PRECEDENTS" blocks
  // (already shown in the detail cards below the IRAC grid)
  const text = content
    .replace(/APPLICABLE SECTIONS[\s\S]*/i, "")
    .replace(/\s+/g, " ")
    .trim();

  /* ── Issue: intro sentence + bulleted questions ── */
  if (sectionKey === "issue") {
    const colonPos = text.search(/:\s+(?=.+\?)/);
    if (colonPos !== -1) {
      const intro = text.slice(0, colonPos + 1);
      const qs = text
        .slice(colonPos + 1)
        .split("?")
        .map((q) => q.trim())
        .filter((q) => q.length > 5)
        .map((q) => q + "?");
      if (qs.length >= 2) {
        return (
          <div className="space-y-3">
            <p className="text-xs text-gray-500 dark:text-slate-400 italic leading-relaxed">
              <Cite text={intro} />
            </p>
            <ul className="space-y-2">
              {qs.map((q, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-blue-400 dark:bg-blue-500 flex-shrink-0" />
                  <span className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed">
                    <Cite text={q} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      }
    }
  }

  /* ── Application: intro + bulleted sentences ── */
  if (sectionKey === "application") {
    const followsMatch = text.match(/^(.{0,150}?(?:follows|following)\s*:)\s*([\s\S]+)/i);
    const intro = followsMatch ? followsMatch[1] : null;
    const bodyText = followsMatch
      ? followsMatch[2].replace(/\s+/g, " ").trim()
      : text;
    const bodySentences = splitSentences(bodyText);
    if (bodySentences.length >= 2) {
      return (
        <div className="space-y-3">
          {intro && (
            <p className="text-xs text-gray-500 dark:text-slate-400 italic leading-relaxed">
              <Cite text={intro} />
            </p>
          )}
          <ul className="space-y-2">
            {bodySentences.map((s, i) => (
              <li key={i} className="flex items-start gap-2.5">
                <span className="mt-[7px] w-1.5 h-1.5 rounded-full bg-amber-400 dark:bg-amber-500 flex-shrink-0" />
                <span className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed">
                  <Cite text={s} />
                </span>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  }

  /* ── Rule + Conclusion + fallback: paragraph chunks ── */
  const sentences = splitSentences(text);
  const chunks: string[] = [];
  for (let i = 0; i < sentences.length; i += 2) {
    chunks.push(sentences.slice(i, i + 2).join(" "));
  }
  if (chunks.length === 0) chunks.push(text);
  return (
    <div className="space-y-2.5">
      {chunks.map((chunk, i) => (
        <p key={i} className="text-sm text-gray-700 dark:text-slate-300 leading-relaxed">
          <Cite text={chunk} />
        </p>
      ))}
    </div>
  );
}

/* ─── IRAC card ───────────────────────────────────────────────── */

const IRAC_CONFIG: Array<{
  letter: string;
  label: string;
  key: IRACKey;
  icon: string;
  accent: string;
  headerBg: string;
  border: string;
  badge: string;
}> = [
  {
    letter: "I",
    label: "Issue",
    key: "issue",
    icon: "help_outline",
    accent: "text-blue-600 dark:text-blue-400",
    headerBg: "bg-blue-50 dark:bg-blue-500/10 border-b border-blue-200 dark:border-blue-500/20",
    border: "border-blue-200 dark:border-blue-500/30",
    badge: "bg-blue-100 dark:bg-blue-500/25 text-blue-700 dark:text-blue-300",
  },
  {
    letter: "R",
    label: "Rule",
    key: "rule",
    icon: "menu_book",
    accent: "text-violet-600 dark:text-violet-400",
    headerBg: "bg-violet-50 dark:bg-violet-500/10 border-b border-violet-200 dark:border-violet-500/20",
    border: "border-violet-200 dark:border-violet-500/30",
    badge: "bg-violet-100 dark:bg-violet-500/25 text-violet-700 dark:text-violet-300",
  },
  {
    letter: "A",
    label: "Application",
    key: "application",
    icon: "balance",
    accent: "text-amber-600 dark:text-amber-400",
    headerBg: "bg-amber-50 dark:bg-amber-500/10 border-b border-amber-200 dark:border-amber-500/20",
    border: "border-amber-200 dark:border-amber-500/30",
    badge: "bg-amber-100 dark:bg-amber-500/25 text-amber-700 dark:text-amber-300",
  },
  {
    letter: "C",
    label: "Conclusion",
    key: "conclusion",
    icon: "task_alt",
    accent: "text-emerald-600 dark:text-emerald-400",
    headerBg: "bg-emerald-50 dark:bg-emerald-500/10 border-b border-emerald-200 dark:border-emerald-500/20",
    border: "border-emerald-200 dark:border-emerald-500/30",
    badge: "bg-emerald-100 dark:bg-emerald-500/25 text-emerald-700 dark:text-emerald-300",
  },
];

function IRACCard({
  letter, label, content, icon, accent, headerBg, border, badge, sectionKey,
}: {
  letter: string; label: string; content: string; icon: string;
  accent: string; headerBg: string; border: string; badge: string;
  sectionKey: IRACKey;
}) {
  return (
    <div className={cn("rounded-xl border overflow-hidden shadow-sm", border)}>
      <div className={cn("px-4 py-3 flex items-center gap-3", headerBg)}>
        <div className={cn("w-7 h-7 rounded-md flex items-center justify-center text-sm font-black flex-shrink-0", badge)}>
          {letter}
        </div>
        <span className={cn("material-symbols-outlined text-[16px]", accent)}>{icon}</span>
        <span className={cn("text-sm font-bold tracking-wide", accent)}>{label}</span>
      </div>
      <div className="px-5 py-4 bg-white dark:bg-[#0f172a] min-h-[100px]">
        <IRACContent content={content} sectionKey={sectionKey} />
      </div>
    </div>
  );
}

/* ─── Input class ─────────────────────────────────────────────── */

const inputCls =
  "w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm text-gray-800 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:border-primary/60 transition-colors";

type ActiveTab = "search" | "analyze";

/* ─── Page ───────────────────────────────────────────────────── */

export default function CasesPage() {
  const { user } = useAuthStore();
  const canAnalyze = user?.role === "lawyer" || user?.role === "legal_advisor" || user?.role === "admin";

  const [tab, setTab] = useState<ActiveTab>("search");

  /* Search state */
  const [searchQuery, setSearchQuery] = useState("");
  const [actFilter, setActFilter] = useState("");
  const [fromYear, setFromYear] = useState("");
  const [toYear, setToYear] = useState("");
  const [topK, setTopK] = useState("10");
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<CaseSearchResponse | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseResult | null>(null);

  /* Analysis state */
  const [scenario, setScenario] = useState("");
  const [caseCitation, setCaseCitation] = useState("");
  const [applicableActs, setApplicableActs] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<CaseAnalysisResponse | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSelectedCase(null);
    setSearchResult(null);
    try {
      const req: CaseSearchRequest = {
        query: searchQuery,
        top_k: parseInt(topK),
        act_filter: actFilter || undefined,
        from_year: fromYear ? parseInt(fromYear) : undefined,
        to_year: toYear ? parseInt(toYear) : undefined,
      };
      const data = await casesAPI.search(req);
      setSearchResult(data);
      if (data.results.length === 0) toast("No cases found. Try broadening your search.", { icon: "🔍" });
    } catch {
      toast.error("Case search failed. Please try again.");
    } finally {
      setSearching(false);
    }
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scenario.trim()) return;
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const req: CaseAnalysisRequest = {
        scenario,
        case_citation: caseCitation || undefined,
        applicable_acts: applicableActs
          ? applicableActs.split(",").map((s) => s.trim()).filter(Boolean)
          : undefined,
      };
      const data = await casesAPI.analyze(req);
      setAnalysis(data);
    } catch {
      toast.error("IRAC analysis failed. Please try again.");
    } finally {
      setAnalyzing(false);
    }
  };

  return (
    <div className="p-4 sm:p-5 lg:p-8 min-h-full">
      <div className="max-w-7xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">Case Law Research</h1>
            <p className="text-gray-500 dark:text-slate-400 text-sm mt-0.5">
              Search precedents and run IRAC analysis on legal scenarios
            </p>
          </div>
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-xs text-gray-500 dark:text-slate-400">
            <span className="material-symbols-outlined text-[14px] text-primary">verified</span>
            All results cross-verified
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 dark:bg-slate-800/60 rounded-xl p-1 w-fit border border-gray-200 dark:border-slate-700">
          {(["search", ...(canAnalyze ? ["analyze"] : [])] as ActiveTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 sm:px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
                tab === t ? "bg-primary text-white shadow" : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
              )}
            >
              {t === "search" ? (
                <span className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[15px]">search</span>
                  Case Search
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[15px]">psychology</span>
                  IRAC Analysis
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── Case Search Tab ─────────────────────────────────── */}
        {tab === "search" && (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            <div className={cn("space-y-4", selectedCase ? "lg:col-span-3" : "lg:col-span-5")}>
              <form onSubmit={handleSearch} className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-4 space-y-4 shadow-sm">
                <div className="flex gap-2 sm:gap-3">
                  <div className="flex-1 relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500 text-[18px]">search</span>
                    <input
                      type="text"
                      placeholder="Search by case name, issue, principle, or keyword…"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg pl-9 pr-4 py-2.5 text-sm text-gray-800 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:border-primary/60 transition-colors"
                      required
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={searching || !searchQuery.trim()}
                    className="flex items-center gap-1.5 px-3 sm:px-4 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:pointer-events-none flex-shrink-0"
                  >
                    {searching
                      ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      : <span className="material-symbols-outlined text-[16px]">manage_search</span>}
                    <span className="hidden sm:inline">Search</span>
                  </button>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: "Act Filter", value: actFilter, onChange: setActFilter, placeholder: "e.g. IPC, BNS", type: "text" },
                    { label: "From Year", value: fromYear, onChange: setFromYear, placeholder: "e.g. 2000", type: "number" },
                    { label: "To Year",   value: toYear,   onChange: setToYear,   placeholder: "e.g. 2024", type: "number" },
                  ].map((f) => (
                    <div key={f.label}>
                      <label className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wider font-medium block mb-1">{f.label}</label>
                      <input
                        type={f.type}
                        placeholder={f.placeholder}
                        value={f.value}
                        onChange={(e) => f.onChange(e.target.value)}
                        className={inputCls + " py-2 text-xs"}
                      />
                    </div>
                  ))}
                  <div>
                    <label className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wider font-medium block mb-1">Results</label>
                    <select value={topK} onChange={(e) => setTopK(e.target.value)} className={inputCls + " py-2 text-xs"}>
                      {["5", "10", "15", "20"].map((v) => <option key={v} value={v}>{v} results</option>)}
                    </select>
                  </div>
                </div>
              </form>

              {searching && (
                <div className="flex justify-center py-16">
                  <div className="text-center space-y-3">
                    <span className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin block mx-auto" />
                    <p className="text-gray-500 dark:text-slate-400 text-sm">Searching case law database…</p>
                  </div>
                </div>
              )}

              {!searching && searchResult && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between px-1">
                    <p className="text-xs text-gray-500 dark:text-slate-500">
                      {searchResult.total_found} case{searchResult.total_found !== 1 ? "s" : ""} found
                      <span className="ml-2 text-gray-400 dark:text-slate-600">({searchResult.search_time_ms}ms)</span>
                    </p>
                    {selectedCase && (
                      <button onClick={() => setSelectedCase(null)} className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white flex items-center gap-1">
                        <span className="material-symbols-outlined text-[13px]">close</span>
                        Close detail
                      </button>
                    )}
                  </div>
                  {searchResult.results.map((c, i) => (
                    <CaseCard
                      key={i}
                      c={c}
                      selected={selectedCase?.citation === c.citation}
                      onSelect={() => setSelectedCase(selectedCase?.citation === c.citation ? null : c)}
                    />
                  ))}
                </div>
              )}

              {!searching && !searchResult && (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                  <span className="material-symbols-outlined text-gray-200 dark:text-slate-700 text-6xl">gavel</span>
                  <p className="text-gray-500 dark:text-slate-400 text-sm mt-3 font-medium">Search Indian Case Law</p>
                  <p className="text-gray-400 dark:text-slate-600 text-xs mt-1 max-w-xs">
                    Enter a legal issue, principle, act section, or case name to find relevant precedents.
                  </p>
                </div>
              )}
            </div>

            {/* Case detail panel */}
            {selectedCase && (
              <div className="lg:col-span-2">
                <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 space-y-5 sticky top-6 shadow-sm">
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="text-base font-bold text-gray-900 dark:text-white leading-snug">{selectedCase.case_name}</h2>
                    <button onClick={() => setSelectedCase(null)} className="flex-shrink-0 text-gray-400 dark:text-slate-500 hover:text-gray-700 dark:hover:text-white transition-colors">
                      <span className="material-symbols-outlined text-[18px]">close</span>
                    </button>
                  </div>

                  <div className="space-y-2">
                    {[
                      { icon: "receipt_long",    label: "Citation",  value: selectedCase.citation,     mono: true },
                      { icon: "account_balance", label: "Court",     value: selectedCase.court,         mono: false },
                      { icon: "calendar_today",  label: "Judgment",  value: selectedCase.judgment_date, mono: false },
                      { icon: "category",        label: "Domain",    value: selectedCase.legal_domain,  mono: false },
                    ].map((m) => (
                      <div key={m.label} className="flex items-center gap-2 text-xs">
                        <span className="material-symbols-outlined text-gray-400 dark:text-slate-500 text-[14px]">{m.icon}</span>
                        <span className="text-gray-500 dark:text-slate-400">{m.label}:</span>
                        <span className={cn("text-gray-900 dark:text-white capitalize", m.mono && "font-mono")}>{m.value}</span>
                      </div>
                    ))}
                    <div className="flex items-start gap-2 text-xs">
                      <span className="material-symbols-outlined text-gray-400 dark:text-slate-500 text-[14px] mt-0.5">person</span>
                      <span className="text-gray-500 dark:text-slate-400 flex-shrink-0">Judges:</span>
                      <span className="text-gray-900 dark:text-white">{selectedCase.judges.join(", ")}</span>
                    </div>
                  </div>

                  <div>
                    <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-1.5">Relevance</p>
                    <RelevanceBar score={selectedCase.relevance_score} />
                  </div>

                  <div>
                    <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-2">Summary</p>
                    <p className="text-xs text-gray-600 dark:text-slate-300 leading-relaxed">{selectedCase.summary}</p>
                  </div>

                  {selectedCase.sections_cited.length > 0 && (
                    <div>
                      <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wider font-medium mb-2">Sections Cited</p>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedCase.sections_cited.map((s) => (
                          <span key={s} className="text-[10px] px-2 py-1 rounded bg-primary/10 text-primary border border-primary/20 font-mono">{s}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {canAnalyze && (
                    <button
                      onClick={() => { setCaseCitation(selectedCase.citation); setTab("analyze"); }}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary/10 border border-primary/30 text-primary text-sm font-medium hover:bg-primary/20 transition-colors"
                    >
                      <span className="material-symbols-outlined text-[16px]">psychology</span>
                      Run IRAC Analysis
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── IRAC Analysis Tab ──────────────────────────────── */}
        {tab === "analyze" && canAnalyze && (
          <div className="space-y-5">

            {/* Input form — compact full-width card */}
            <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-4">
                <span className="material-symbols-outlined text-primary text-[20px]">psychology</span>
                <h2 className="text-base font-semibold text-gray-900 dark:text-white">IRAC Legal Analysis</h2>
                <span className="text-xs text-gray-400 dark:text-slate-500 ml-auto hidden sm:block">
                  Multi-agent AI reasoning pipeline
                </span>
              </div>

              <form onSubmit={handleAnalyze} className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-600 dark:text-slate-400 block mb-1.5">
                    Legal Scenario <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value)}
                    placeholder="Describe the facts of the case, the parties involved, the legal dispute, and what relief is being sought…"
                    rows={5}
                    required
                    className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-4 py-3 text-sm text-gray-800 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:border-primary/60 transition-colors resize-none leading-relaxed"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs font-medium text-gray-600 dark:text-slate-400 block mb-1.5">
                      Case Citation <span className="text-gray-400 font-normal">(optional)</span>
                    </label>
                    <input
                      type="text"
                      value={caseCitation}
                      onChange={(e) => setCaseCitation(e.target.value)}
                      placeholder="e.g. (2019) 5 SCC 1"
                      className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2.5 text-sm text-gray-800 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:border-primary/60 transition-colors font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-600 dark:text-slate-400 block mb-1.5">
                      Applicable Acts <span className="text-gray-400 font-normal">(comma-separated)</span>
                    </label>
                    <input
                      type="text"
                      value={applicableActs}
                      onChange={(e) => setApplicableActs(e.target.value)}
                      placeholder="IPC, CrPC, Evidence Act, BNS"
                      className="w-full bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2.5 text-sm text-gray-800 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:border-primary/60 transition-colors"
                    />
                  </div>
                  <div className="flex items-end">
                    <button
                      type="submit"
                      disabled={analyzing || !scenario.trim()}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:pointer-events-none"
                    >
                      {analyzing
                        ? <><span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> Analysing…</>
                        : <><span className="material-symbols-outlined text-[17px]">analytics</span> Run Analysis</>}
                    </button>
                  </div>
                </div>
              </form>
            </div>

            {/* Loading state */}
            {analyzing && (
              <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-10 shadow-sm">
                <div className="max-w-sm mx-auto text-center space-y-6">
                  <div className="w-14 h-14 rounded-full bg-primary/10 border-2 border-primary/30 flex items-center justify-center mx-auto">
                    <span className="material-symbols-outlined text-primary text-[24px] animate-pulse">psychology</span>
                  </div>
                  <div>
                    <p className="text-gray-900 dark:text-white font-semibold">Applying IRAC Framework</p>
                    <p className="text-gray-500 dark:text-slate-400 text-xs mt-1">
                      Multi-agent pipeline is reasoning through your scenario…
                    </p>
                  </div>
                  <div className="space-y-3 text-left">
                    {[
                      { step: "Issue Identification", desc: "Extracting core legal questions" },
                      { step: "Rule Retrieval",       desc: "Finding applicable statutes & precedents" },
                      { step: "Fact Application",     desc: "Mapping law to the facts" },
                      { step: "Conclusion",           desc: "Formulating legal outcome" },
                    ].map(({ step, desc }, i) => (
                      <div key={i} className="flex items-center gap-3">
                        <span className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin flex-shrink-0" />
                        <div>
                          <span className="text-xs font-medium text-gray-700 dark:text-slate-300">{step}</span>
                          <span className="text-xs text-gray-400 dark:text-slate-500 ml-1.5">— {desc}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Analysis results */}
            {!analyzing && analysis && (
              <div className="space-y-4">

                {/* Summary strip */}
                <div className="flex flex-wrap items-center gap-3 px-1">
                  <span className={cn("text-xs px-3 py-1 rounded-full border font-medium", getVerificationColor(analysis.verification_status))}>
                    {analysis.verification_status === "VERIFIED"
                      ? "✓ Fully Verified"
                      : analysis.verification_status === "PARTIALLY_VERIFIED"
                      ? "~ Partially Verified"
                      : "✗ Unverified"}
                  </span>
                  <span className={cn("text-xs font-semibold capitalize", getConfidenceColor(analysis.confidence))}>
                    {analysis.confidence} confidence
                  </span>
                  {analysis.applicable_sections.length > 0 && (
                    <span className="text-xs text-gray-400 dark:text-slate-500 flex items-center gap-1">
                      <span className="material-symbols-outlined text-[12px]">gavel</span>
                      {analysis.applicable_sections.length} section{analysis.applicable_sections.length !== 1 ? "s" : ""} cited
                    </span>
                  )}
                  {analysis.applicable_precedents.length > 0 && (
                    <span className="text-xs text-gray-400 dark:text-slate-500 flex items-center gap-1">
                      <span className="material-symbols-outlined text-[12px]">history_edu</span>
                      {analysis.applicable_precedents.length} precedent{analysis.applicable_precedents.length !== 1 ? "s" : ""} applied
                    </span>
                  )}
                </div>

                {/* IRAC 2×2 grid */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {IRAC_CONFIG.map((cfg) => (
                    <IRACCard
                      key={cfg.key}
                      letter={cfg.letter}
                      label={cfg.label}
                      content={analysis.irac_analysis[cfg.key]}
                      icon={cfg.icon}
                      accent={cfg.accent}
                      headerBg={cfg.headerBg}
                      border={cfg.border}
                      badge={cfg.badge}
                      sectionKey={cfg.key}
                    />
                  ))}
                </div>

                {/* Supporting details — sections + precedents */}
                {(analysis.applicable_sections.length > 0 || analysis.applicable_precedents.length > 0) && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

                    {analysis.applicable_sections.length > 0 && (
                      <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-4 shadow-sm">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="material-symbols-outlined text-[15px] text-gray-400 dark:text-slate-500">gavel</span>
                          <p className="text-xs font-semibold text-gray-600 dark:text-slate-400 uppercase tracking-wider">Applicable Sections</p>
                        </div>
                        <div className="divide-y divide-gray-100 dark:divide-slate-800">
                          {analysis.applicable_sections.map((s, i) => (
                            <div key={i} className="flex items-center justify-between py-2 first:pt-0 last:pb-0">
                              <div>
                                <span className="text-xs font-mono font-semibold text-gray-800 dark:text-slate-200">
                                  {s.act_code} §{s.section_number}
                                </span>
                                {s.section_title && (
                                  <span className="text-xs text-gray-500 dark:text-slate-400 ml-2">{s.section_title}</span>
                                )}
                              </div>
                              <span className={cn(
                                "text-[10px] px-2 py-0.5 rounded-full border font-medium",
                                s.verification === "VERIFIED"
                                  ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20"
                                  : s.verification === "VERIFIED_INCOMPLETE"
                                  ? "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-500/20"
                                  : "bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border-red-200 dark:border-red-500/20"
                              )}>
                                {s.verification === "VERIFIED"
                                  ? "Verified"
                                  : s.verification === "VERIFIED_INCOMPLETE"
                                  ? "Partial"
                                  : "Not Found"}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {analysis.applicable_precedents.length > 0 && (
                      <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-4 shadow-sm">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="material-symbols-outlined text-[15px] text-gray-400 dark:text-slate-500">history_edu</span>
                          <p className="text-xs font-semibold text-gray-600 dark:text-slate-400 uppercase tracking-wider">Precedents Applied</p>
                        </div>
                        <div className="space-y-3">
                          {analysis.applicable_precedents.map((p, i) => (
                            <div key={i} className="border-l-2 border-primary/40 pl-3 py-0.5">
                              <p className="text-xs font-semibold text-gray-800 dark:text-slate-200">
                                {p.case_name}
                                <span className="text-gray-400 dark:text-slate-500 font-normal ml-1.5">({p.year})</span>
                              </p>
                              <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 leading-relaxed">{p.relevance}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                  </div>
                )}
              </div>
            )}

            {/* Empty state */}
            {!analyzing && !analysis && (
              <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-12 flex flex-col items-center justify-center text-center shadow-sm">
                <div className="grid grid-cols-2 gap-2 mb-6">
                  {[
                    { letter: "I", bg: "bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300" },
                    { letter: "R", bg: "bg-violet-100 dark:bg-violet-500/20 text-violet-700 dark:text-violet-300" },
                    { letter: "A", bg: "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300" },
                    { letter: "C", bg: "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300" },
                  ].map(({ letter, bg }) => (
                    <div key={letter} className={cn("w-10 h-10 rounded-lg flex items-center justify-center text-lg font-black opacity-25", bg)}>
                      {letter}
                    </div>
                  ))}
                </div>
                <p className="text-gray-500 dark:text-slate-400 text-sm font-medium">No Analysis Yet</p>
                <p className="text-gray-400 dark:text-slate-600 text-xs mt-1.5 max-w-xs leading-relaxed">
                  Describe your legal scenario above and click <strong className="text-gray-500 dark:text-slate-400">Run Analysis</strong> to generate structured IRAC legal reasoning.
                </p>
              </div>
            )}

          </div>
        )}

        {/* Role-restricted notice */}
        {tab === "analyze" && !canAnalyze && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <span className="material-symbols-outlined text-gray-200 dark:text-slate-700 text-5xl">lock</span>
            <p className="text-gray-500 dark:text-slate-400 text-sm mt-3 font-medium">IRAC Analysis — Restricted Access</p>
            <p className="text-gray-400 dark:text-slate-600 text-xs mt-1 max-w-xs">
              IRAC analysis is available for Lawyers, Legal Advisors, and Admins only.
            </p>
          </div>
        )}

      </div>
    </div>
  );
}
