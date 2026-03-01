"use client";

import { useState, useEffect } from "react";
import { sectionsAPI } from "@/lib/api";
import type { ActInfo, SectionDetail } from "@/types";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

// ── Acts quick-pick list ───────────────────────────────────────────────
const QUICK_ACTS = [
  { code: "BNS_2023",  label: "BNS",   full: "Bharatiya Nyaya Sanhita 2023",         era: "new" },
  { code: "BNSS_2023", label: "BNSS",  full: "Bharatiya Nagarik Suraksha Sanhita 2023", era: "new" },
  { code: "BSA_2023",  label: "BSA",   full: "Bharatiya Sakshya Adhiniyam 2023",     era: "new" },
  { code: "IPC_1860",  label: "IPC",   full: "Indian Penal Code 1860",               era: "legacy" },
  { code: "CRPC_1973", label: "CrPC",  full: "Code of Criminal Procedure 1973",      era: "legacy" },
  { code: "IEA_1872",  label: "IEA",   full: "Indian Evidence Act 1872",             era: "legacy" },
];

// ── Parse legal text into structured clauses ───────────────────────────
function parseLegalText(text: string): { tag: string; text: string }[] {
  if (!text) return [];
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  return lines.map((line) => {
    if (/^\(\d+\)/.test(line)) return { tag: "clause", text: line };
    if (/^\([a-z]\)/.test(line)) return { tag: "sub", text: line };
    if (/^Explanation/i.test(line)) return { tag: "explanation", text: line };
    if (/^Provided/i.test(line)) return { tag: "proviso", text: line };
    return { tag: "body", text: line };
  });
}

// ── Structured Legal Text Component ───────────────────────────────────
function LegalTextDisplay({ text }: { text: string }) {
  const clauses = parseLegalText(text);
  if (!clauses.length) return null;
  return (
    <div className="space-y-2 text-sm">
      {clauses.map((c, i) => {
        if (c.tag === "clause") {
          return (
            <div key={i} className="flex gap-3">
              <span className="flex-shrink-0 w-8 h-6 flex items-center justify-center rounded bg-primary/10 text-primary text-[11px] font-bold mt-0.5">
                {c.text.match(/^\((\d+)\)/)?.[1]}
              </span>
              <p className="text-gray-800 dark:text-slate-200 leading-relaxed">
                {c.text.replace(/^\(\d+\)\s*/, "")}
              </p>
            </div>
          );
        }
        if (c.tag === "sub") {
          return (
            <div key={i} className="flex gap-3 ml-6">
              <span className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 text-[11px] font-bold mt-0.5">
                {c.text.match(/^\(([a-z])\)/)?.[1]}
              </span>
              <p className="text-gray-700 dark:text-slate-300 leading-relaxed">
                {c.text.replace(/^\([a-z]\)\s*/, "")}
              </p>
            </div>
          );
        }
        if (c.tag === "explanation") {
          return (
            <div key={i} className="ml-2 pl-3 border-l-2 border-amber-400/40 bg-amber-50/50 dark:bg-amber-400/5 rounded-r py-1.5 pr-3">
              <p className="text-amber-700 dark:text-amber-400 text-xs font-semibold uppercase tracking-wide mb-0.5">Explanation</p>
              <p className="text-gray-700 dark:text-slate-300 leading-relaxed">
                {c.text.replace(/^Explanation\s*[-—:.\d]*/i, "").trim()}
              </p>
            </div>
          );
        }
        if (c.tag === "proviso") {
          return (
            <div key={i} className="ml-2 pl-3 border-l-2 border-blue-400/40 bg-blue-50/50 dark:bg-blue-400/5 rounded-r py-1.5 pr-3">
              <p className="text-blue-700 dark:text-blue-400 text-xs font-semibold uppercase tracking-wide mb-0.5">Proviso</p>
              <p className="text-gray-700 dark:text-slate-300 leading-relaxed">
                {c.text.replace(/^Provided\s*that/i, "").trim()}
              </p>
            </div>
          );
        }
        return (
          <p key={i} className="text-gray-800 dark:text-slate-200 leading-relaxed">{c.text}</p>
        );
      })}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────
export default function StatutesPage() {
  const [acts, setActs] = useState<ActInfo[]>([]);
  const [selectedActCode, setSelectedActCode] = useState("BNS_2023");
  const [section, setSection] = useState("");
  const [sectionDetail, setSectionDetail] = useState<SectionDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    sectionsAPI.listActs()
      .then((d) => setActs(d.acts))
      .catch(() => {});
  }, []);

  const allActOptions = [
    ...QUICK_ACTS,
    ...acts
      .filter((a) => !QUICK_ACTS.some((q) => q.code === a.act_code))
      .map((a) => ({ code: a.act_code, label: a.short_name || a.act_code, full: a.act_name, era: a.era || "legacy" })),
  ];

  const handleLookup = async () => {
    if (!selectedActCode || !section.trim()) {
      toast.error("Select an act and enter a section number.");
      return;
    }
    setLoading(true);
    setSectionDetail(null);
    try {
      const data = await sectionsAPI.getSection(selectedActCode, section.trim());
      setSectionDetail(data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) toast.error(`Section ${selectedActCode} §${section} not found in database.`);
      else toast.error("Lookup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const selectedActInfo = allActOptions.find((a) => a.code === selectedActCode);

  return (
    <div className="p-4 sm:p-6 lg:p-8 min-h-full">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">Statutes &amp; Acts</h1>
          <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
            Look up statutory provisions across BNS, BNSS, BSA, IPC, CrPC, and IEA.
          </p>
        </div>

        {/* ── LOOKUP ──────────────────────────────────────────────── */}
        <div className="space-y-5 animate-fade-in">

            {/* Act Selector Pills */}
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-slate-500 uppercase tracking-wider mb-2">Select Act</p>
              <div className="flex flex-wrap gap-2">
                {QUICK_ACTS.map((act) => (
                  <button
                    key={act.code}
                    onClick={() => { setSelectedActCode(act.code); setSectionDetail(null); }}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-xl border text-sm font-semibold transition-all",
                      selectedActCode === act.code
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-gray-200 dark:border-slate-700 bg-white dark:bg-[#0f172a] text-gray-600 dark:text-slate-300 hover:border-primary/40"
                    )}
                  >
                    <span className={cn(
                      "text-[10px] font-bold px-1.5 py-0.5 rounded",
                      act.era === "new"
                        ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400"
                        : "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400"
                    )}>
                      {act.era === "new" ? "NEW" : "OLD"}
                    </span>
                    {act.label}
                  </button>
                ))}
                {/* Dropdown for other acts */}
                {acts.filter((a) => !QUICK_ACTS.some((q) => q.code === a.act_code)).length > 0 && (
                  <select
                    value={QUICK_ACTS.some((q) => q.code === selectedActCode) ? "" : selectedActCode}
                    onChange={(e) => { if (e.target.value) { setSelectedActCode(e.target.value); setSectionDetail(null); } }}
                    className="px-3 py-2 rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-[#0f172a] text-sm text-gray-600 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50"
                  >
                    <option value="">More Acts…</option>
                    {acts.filter((a) => !QUICK_ACTS.some((q) => q.code === a.act_code)).map((a) => (
                      <option key={a.act_code} value={a.act_code}>{a.short_name || a.act_code}</option>
                    ))}
                  </select>
                )}
              </div>
              {selectedActInfo && (
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-1.5">{selectedActInfo.full}</p>
              )}
            </div>

            {/* Section Number Search Bar */}
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <label className="text-xs font-semibold text-gray-500 dark:text-slate-500 uppercase tracking-wider block mb-1.5">
                  Section Number
                </label>
                <div className="relative">
                  <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500 text-[20px] pointer-events-none">
                    tag
                  </span>
                  <input
                    type="text"
                    value={section}
                    onChange={(e) => setSection(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                    placeholder={`e.g. 103, 482, 63A`}
                    className="w-full pl-10 pr-4 h-11 rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-[#0f172a] text-gray-800 dark:text-slate-100 placeholder-gray-400 dark:placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                  />
                </div>
              </div>
              <button
                onClick={handleLookup}
                disabled={loading || !selectedActCode || !section.trim()}
                className="h-11 flex items-center gap-2 px-5 rounded-xl bg-primary text-white font-bold hover:bg-amber-600 transition-all disabled:opacity-40 disabled:pointer-events-none shadow-sm"
              >
                {loading
                  ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  : <span className="material-symbols-outlined text-[20px]">search</span>
                }
                <span className="hidden sm:inline">Search</span>
              </button>
            </div>

            {/* Quick Section Examples */}
            <div className="flex flex-wrap gap-2">
              {[
                { act: "BNS_2023",  sec: "103",  label: "BNS 103 · Murder" },
                { act: "BNS_2023",  sec: "64",   label: "BNS 64 · Rape" },
                { act: "BNSS_2023", sec: "482",  label: "BNSS 482 · Anticipatory Bail" },
                { act: "IPC_1860",  sec: "302",  label: "IPC 302 · Murder" },
                { act: "IPC_1860",  sec: "420",  label: "IPC 420 · Cheating" },
              ].map((ex) => (
                <button
                  key={ex.label}
                  onClick={() => { setSelectedActCode(ex.act); setSection(ex.sec); setSectionDetail(null); }}
                  className="px-2.5 py-1 rounded-full border border-gray-200 dark:border-slate-700 text-xs text-gray-600 dark:text-slate-400 hover:border-primary/40 hover:text-primary hover:bg-primary/5 transition-all"
                >
                  {ex.label}
                </button>
              ))}
            </div>

            {/* ── Section Detail Card ────────────────────────────── */}
            {sectionDetail && (
              <div className="bg-white dark:bg-[#0f172a] rounded-2xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm animate-fade-in">

                {/* Card Header */}
                <div className="px-5 py-4 border-b border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                          §{sectionDetail.section_number}
                        </span>
                        <h2 className="text-base font-bold text-gray-900 dark:text-white">
                          {sectionDetail.section_title}
                        </h2>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-slate-500 mt-1">
                        {sectionDetail.act_name}
                        {sectionDetail.chapter && (
                          <> · Chapter {sectionDetail.chapter}
                            {sectionDetail.chapter_title && ` — ${sectionDetail.chapter_title}`}
                          </>
                        )}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
                      {sectionDetail.is_offence && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-400/10 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-400/20 font-bold uppercase tracking-wide">
                          Offence
                        </span>
                      )}
                      {sectionDetail.is_bailable !== undefined && (
                        <span className={cn(
                          "text-[10px] px-2 py-0.5 rounded-full border font-bold uppercase tracking-wide",
                          sectionDetail.is_bailable
                            ? "bg-emerald-50 dark:bg-emerald-400/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-400/20"
                            : "bg-amber-50 dark:bg-amber-400/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-400/20"
                        )}>
                          {sectionDetail.is_bailable ? "Bailable" : "Non-Bailable"}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Legal Text */}
                <div className="px-5 py-5">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-slate-500 mb-3 flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[14px]">gavel</span>
                    Legal Provision
                  </p>
                  <LegalTextDisplay text={sectionDetail.legal_text} />
                </div>

                {/* Metadata Grid */}
                <div className="px-5 pb-5 grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {sectionDetail.is_cognizable !== undefined && (
                    <div className="p-3 rounded-xl bg-gray-50 dark:bg-slate-900 border border-gray-100 dark:border-slate-800 text-center">
                      <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wide font-semibold mb-1">Cognizable</p>
                      <span className={cn(
                        "text-sm font-bold",
                        sectionDetail.is_cognizable ? "text-emerald-600 dark:text-emerald-400" : "text-gray-500 dark:text-slate-400"
                      )}>
                        {sectionDetail.is_cognizable ? "Yes" : "No"}
                      </span>
                    </div>
                  )}
                  {sectionDetail.triable_by && (
                    <div className="p-3 rounded-xl bg-gray-50 dark:bg-slate-900 border border-gray-100 dark:border-slate-800 text-center sm:col-span-2">
                      <p className="text-[10px] text-gray-400 dark:text-slate-500 uppercase tracking-wide font-semibold mb-1">Triable By</p>
                      <span className="text-sm font-semibold text-gray-800 dark:text-slate-200">{sectionDetail.triable_by}</span>
                    </div>
                  )}
                </div>

                {/* Replaces */}
                {sectionDetail.replaces && sectionDetail.replaces.length > 0 && (
                  <div className="px-5 pb-4 flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-gray-400 dark:text-slate-500 font-medium">Replaces:</span>
                    {sectionDetail.replaces.map((r, i) => (
                      <button
                        key={i}
                        onClick={() => { setSelectedActCode(r.act_code); setSection(r.section_number); setSectionDetail(null); }}
                        className="text-xs text-primary font-semibold hover:underline"
                      >
                        {r.act_code.split("_")[0]} §{r.section_number}
                      </button>
                    ))}
                  </div>
                )}

                {/* Verification footer */}
                <div className="px-5 py-3 border-t border-gray-100 dark:border-slate-800 flex items-center gap-2 text-xs text-gray-400 dark:text-slate-500">
                  <span className="material-symbols-outlined text-emerald-500 text-[14px]">verified</span>
                  {sectionDetail.verification_status} · Extraction confidence: {(sectionDetail.extraction_confidence * 100).toFixed(0)}%
                </div>
              </div>
            )}
        </div>
      </div>
    </div>
  );
}
