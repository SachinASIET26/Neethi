"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { useUIStore } from "@/store/ui";
import { useTranslations } from "@/lib/i18n";
import { queryAPI } from "@/lib/api";
import { formatDate, formatDateTime, getRoleLabel, cn } from "@/lib/utils";
import type { QueryHistoryItem } from "@/types";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";

// ── Helpers ────────────────────────────────────────────────────────────
function greeting(t: { goodMorning: string; goodAfternoon: string; goodEvening: string }) {
  const h = new Date().getHours();
  if (h < 12) return t.goodMorning;
  if (h < 17) return t.goodAfternoon;
  return t.goodEvening;
}

const STATUS_BADGE: Record<string, string> = {
  VERIFIED:           "bg-emerald-50 dark:bg-emerald-400/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-400/20",
  PARTIALLY_VERIFIED: "bg-amber-50  dark:bg-amber-400/10  text-amber-600  dark:text-amber-400  border-amber-200  dark:border-amber-400/20",
  UNVERIFIED:         "bg-red-50    dark:bg-red-400/10    text-red-600    dark:text-red-400    border-red-200    dark:border-red-400/20",
};

// ── Custom Tooltip ─────────────────────────────────────────────────────
function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 shadow-lg text-xs">
      <p className="font-semibold text-gray-700 dark:text-slate-300 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }} className="font-medium">
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
}

// ── Computed helpers ────────────────────────────────────────────────────
function computeWeeklyActivity(items: QueryHistoryItem[]) {
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dayMap: Record<string, number> = {};
  DAYS.forEach((d) => { dayMap[d] = 0; });

  const oneWeekAgo = new Date();
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 6);
  oneWeekAgo.setHours(0, 0, 0, 0);

  items.forEach((q) => {
    const date = new Date(q.created_at);
    if (date >= oneWeekAgo) {
      dayMap[DAYS[date.getDay()]] += 1;
    }
  });

  // Build ordered list: 7 days ending today
  const today = new Date().getDay();
  const result = [];
  for (let i = 6; i >= 0; i--) {
    const dayIdx = (today - i + 7) % 7;
    const name = DAYS[dayIdx];
    result.push({ day: name, queries: dayMap[name] });
  }
  return result;
}

function computeVerification(items: QueryHistoryItem[]) {
  if (!items.length) return null;
  const v = items.filter((q) => q.verification_status === "VERIFIED").length;
  const p = items.filter((q) => q.verification_status === "PARTIALLY_VERIFIED").length;
  const u = items.filter((q) => q.verification_status === "UNVERIFIED").length;
  const total = items.length;
  return [
    { name: "Verified",   value: Math.round((v / total) * 100), color: "#10b981" },
    { name: "Partial",    value: Math.round((p / total) * 100), color: "#f59e0b" },
    { name: "Unverified", value: Math.round((u / total) * 100), color: "#ef4444" },
  ];
}

// ── Main Component ─────────────────────────────────────────────────────
export default function DashboardPage() {
  const { user } = useAuthStore();
  const { selectedLanguage } = useUIStore();
  const t = useTranslations(selectedLanguage);

  const [history, setHistory] = useState<QueryHistoryItem[]>([]);  // recent 5
  const [allHistory, setAllHistory] = useState<QueryHistoryItem[]>([]);
  const [totalQueries, setTotalQueries] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);

  // Fetch recent 5 for the table
  useEffect(() => {
    queryAPI.history(5, 0)
      .then((d) => setHistory(d.queries))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Fetch up to 50 for stats & charts (backend max is 50)
  useEffect(() => {
    queryAPI.history(50, 0)
      .then((d) => {
        setAllHistory(d.queries);
        setTotalQueries(d.total);
      })
      .catch(() => {})
      .finally(() => setStatsLoading(false));
  }, []);

  const isLawyer = user?.role === "lawyer" || user?.role === "legal_advisor";
  const isCitizen = user?.role === "citizen";

  // Computed stats
  const verifiedCount = allHistory.filter((q) => q.verification_status === "VERIFIED").length;
  const oneWeekAgo = new Date(); oneWeekAgo.setDate(oneWeekAgo.getDate() - 6); oneWeekAgo.setHours(0, 0, 0, 0);
  const thisWeekCount = allHistory.filter((q) => new Date(q.created_at) >= oneWeekAgo).length;
  const successCount = allHistory.filter((q) =>
    q.verification_status === "VERIFIED" || q.verification_status === "PARTIALLY_VERIFIED"
  ).length;
  const successRate = allHistory.length > 0 ? Math.round((successCount / allHistory.length) * 100) : 0;

  const weeklyActivity = computeWeeklyActivity(allHistory);
  const verificationData = computeVerification(allHistory);

  const QUICK_ACTIONS = isLawyer
    ? [
        { icon: "edit_note",  label: t.drafting,  href: "/documents/draft" },
        { icon: "analytics",  label: t.cases,     href: "/cases" },
        { icon: "balance",    label: t.statutes,  href: "/statutes" },
        { icon: "summarize",  label: t.history,   href: "/history" },
      ]
    : [
        { icon: "forum",      label: t.legalAssistant,  href: "/query" },
        { icon: "location_on",label: t.resources,       href: "/resources" },
        { icon: "edit_note",  label: t.drafting,        href: "/documents/draft" },
        { icon: "balance",    label: t.statutes,        href: "/statutes" },
      ];

  const STAT_CARDS = [
    {
      label: t.totalConsultations,
      value: statsLoading ? "—" : totalQueries.toLocaleString(),
      icon: "forum",
      color: "text-blue-500",
      bg: "bg-blue-50 dark:bg-blue-500/10",
      border: "border-blue-100 dark:border-blue-500/20",
    },
    {
      label: t.verifiedResponses,
      value: statsLoading ? "—" : verifiedCount.toLocaleString(),
      icon: "verified",
      color: "text-emerald-500",
      bg: "bg-emerald-50 dark:bg-emerald-500/10",
      border: "border-emerald-100 dark:border-emerald-500/20",
    },
    {
      label: t.thisWeek,
      value: statsLoading ? "—" : thisWeekCount.toLocaleString(),
      icon: "calendar_today",
      color: "text-purple-500",
      bg: "bg-purple-50 dark:bg-purple-500/10",
      border: "border-purple-100 dark:border-purple-500/20",
    },
    {
      label: t.successRate,
      value: statsLoading ? "—" : `${successRate}%`,
      icon: "analytics",
      color: "text-primary",
      bg: "bg-primary/5",
      border: "border-primary/10",
    },
  ];

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8 min-h-full">
      <div className="max-w-7xl mx-auto space-y-8">

        {/* ── Header ────────────────────────────────────────────── */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
              {greeting(t)},{" "}
              {user?.role === "lawyer" ? "Counsel " : ""}
              {user?.full_name?.split(" ")[0]}
            </h2>
            <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
              {t.workspaceSubtitle}
            </p>
          </div>
          <div className="text-right flex flex-col items-end gap-1">
            <p className="text-sm text-gray-400 dark:text-slate-500">{formatDate(new Date().toISOString())}</p>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-semibold">
              <span className="material-symbols-outlined text-[14px]">gavel</span>
              {getRoleLabel(user?.role || "citizen")} Plan
            </span>
          </div>
        </div>

        {/* ── KPI Stats ─────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {STAT_CARDS.map((stat) => (
            <div
              key={stat.label}
              className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 hover:border-primary/30 transition-colors shadow-sm"
            >
              <div className="flex items-start justify-between mb-4">
                <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center border", stat.bg, stat.border)}>
                  <span className={cn("material-symbols-outlined text-[20px]", stat.color)}>{stat.icon}</span>
                </div>
              </div>
              {statsLoading ? (
                <div className="w-12 h-7 bg-gray-200 dark:bg-slate-800 rounded animate-pulse mb-1" />
              ) : (
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value}</p>
              )}
              <p className="text-xs text-gray-500 dark:text-slate-500 font-medium mt-1">{stat.label}</p>
            </div>
          ))}
        </div>

        {/* ── Charts Row ────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Weekly Activity Area Chart */}
          <div className="lg:col-span-2 bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white">{t.weeklyActivity}</h3>
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
                  {t.thisWeek}
                </p>
              </div>
              <span className="text-xs text-primary font-semibold bg-primary/10 px-2.5 py-1 rounded-full border border-primary/20">
                7 {selectedLanguage === "en" ? "days" : "d"}
              </span>
            </div>
            {statsLoading ? (
              <div className="h-[200px] flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            ) : weeklyActivity.every((d) => d.queries === 0) ? (
              <div className="h-[200px] flex flex-col items-center justify-center text-center">
                <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-4xl">show_chart</span>
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{t.noData}</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={weeklyActivity} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="queryGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#db7706" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#db7706" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,0.1)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area type="monotone" dataKey="queries" name="Queries" stroke="#db7706" strokeWidth={2} fill="url(#queryGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Verification Pie Chart */}
          <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
            <div className="mb-4">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">{t.verificationRate}</h3>
              <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">Citation accuracy</p>
            </div>
            {statsLoading ? (
              <div className="h-[160px] flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            ) : !verificationData ? (
              <div className="h-[160px] flex flex-col items-center justify-center text-center">
                <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-4xl">donut_large</span>
                <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">{t.noData}</p>
              </div>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={160}>
                  <PieChart>
                    <Pie
                      data={verificationData}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={70}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {verificationData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => `${v}%`} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-2 space-y-1.5">
                  {verificationData.map((d) => (
                    <div key={d.name} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.color }} />
                        <span className="text-gray-600 dark:text-slate-400">{d.name}</span>
                      </div>
                      <span className="font-semibold text-gray-900 dark:text-white">{d.value}%</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── Recent Queries ─────────────────────────────────────── */}
        <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-slate-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-gray-900 dark:text-white">{t.recentLegalQueries}</h3>
            <Link href="/history" className="text-xs text-primary hover:text-amber-600 font-semibold transition-colors">
              {t.viewAll}
            </Link>
          </div>

          {loading ? (
            <div className="p-8 flex justify-center">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : history.length === 0 ? (
            <div className="p-10 text-center">
              <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-5xl">forum</span>
              <p className="text-gray-400 dark:text-slate-500 text-sm mt-2">{t.noQueriesYetDash}</p>
              <Link
                href="/query"
                className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-semibold hover:bg-amber-600 transition-colors"
              >
                <span className="material-symbols-outlined text-[14px]">add</span>
                {t.startQuery}
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-gray-100 dark:divide-slate-800">
              {history.map((q) => (
                <Link
                  key={q.query_id}
                  href={`/query?q=${encodeURIComponent(q.query_text)}`}
                  className="flex items-center gap-4 px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors group"
                >
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="material-symbols-outlined text-primary text-[18px]">forum</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                      {q.query_text}
                    </p>
                    <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">
                      {formatDateTime(q.created_at)}
                    </p>
                  </div>
                  <span className={cn("text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border flex-shrink-0", STATUS_BADGE[q.verification_status] || STATUS_BADGE.UNVERIFIED)}>
                    {q.verification_status === "VERIFIED" ? t.verified :
                     q.verification_status === "PARTIALLY_VERIFIED" ? t.partial : t.unverified}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* ── Quick Actions ─────────────────────────────────────── */}
        <div className={cn(
          "bg-gradient-to-br from-primary/5 to-amber-50/50 dark:from-primary/10 dark:to-primary/5 rounded-xl border border-primary/20 p-6 shadow-sm"
        )}>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
            <div>
              <h3 className="text-base font-bold text-gray-900 dark:text-white">
                {isLawyer ? "Lawyer Toolbox" : isCitizen ? "Quick Actions" : "Quick Actions"}
              </h3>
              <p className="text-sm text-gray-500 dark:text-slate-400 mt-0.5">
                {isLawyer
                  ? "AI-powered shortcuts to expedite your case workflow."
                  : "Get legal help quickly with these common tools."}
              </p>
            </div>
            <Link
              href="/query"
              className="flex-shrink-0 flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-amber-600 transition-colors shadow-sm"
            >
              <span className="material-symbols-outlined text-[18px]">add</span>
              {t.newQuery}
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {QUICK_ACTIONS.map((a) => (
              <Link
                key={a.label}
                href={a.href}
                className="flex flex-col items-center gap-2 bg-white dark:bg-[#0f172a] border border-gray-200 dark:border-slate-800 p-4 rounded-xl text-center hover:border-primary/30 hover:shadow-md transition-all group"
              >
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                  <span className="material-symbols-outlined text-primary text-[22px]">{a.icon}</span>
                </div>
                <span className="text-xs font-semibold text-gray-700 dark:text-slate-300 group-hover:text-gray-900 dark:group-hover:text-white leading-tight">
                  {a.label}
                </span>
              </Link>
            ))}
          </div>
        </div>

        {/* ── Access Info Banner (citizens) ─────────────────────── */}
        {isCitizen && (
          <div className="rounded-xl border border-blue-200 dark:border-blue-500/20 bg-blue-50 dark:bg-blue-500/5 p-5 flex items-start gap-4">
            <div className="w-10 h-10 rounded-xl bg-blue-100 dark:bg-blue-500/20 flex items-center justify-center flex-shrink-0">
              <span className="material-symbols-outlined text-blue-500 text-[22px]">info</span>
            </div>
            <div>
              <h4 className="text-sm font-bold text-gray-900 dark:text-white">Citizen Access</h4>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-1 leading-relaxed">
                You have access to legal queries, document drafting (Legal Notice, FIR, Power of Attorney), nearby legal aid, and statute lookup. For advanced IRAC analysis and bail applications, upgrade to a Lawyer account.
              </p>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
