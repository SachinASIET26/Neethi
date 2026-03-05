"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/store/auth";
import { adminAPI } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AdminStats, HealthResponse } from "@/types";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import toast from "react-hot-toast";

const ROLE_COLORS: Record<string, string> = {
    citizen: "#3b82f6",
    lawyer: "#8b5cf6",
    legal_advisor: "#f59e0b",
    police: "#ef4444",
    admin: "#10b981",
};

const ROLE_LABELS: Record<string, string> = {
    citizen: "Citizen",
    lawyer: "Lawyer",
    legal_advisor: "Legal Advisor",
    police: "Police",
    admin: "Admin",
};

const HEALTH_ICONS: Record<string, string> = {
    database: "storage",
    qdrant: "search",
    redis: "cached",
    groq_api: "smart_toy",
    mistral_api: "auto_awesome",
    anthropic_api: "psychology",
    sarvam_api: "record_voice_over",
};

const STATUS_COLORS: Record<string, string> = {
    healthy: "text-emerald-500",
    degraded: "text-amber-500",
    unavailable: "text-red-500",
    unconfigured: "text-gray-400 dark:text-slate-600",
};

const STATUS_BG: Record<string, string> = {
    healthy: "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/20",
    degraded: "bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/20",
    unavailable: "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20",
    unconfigured: "bg-gray-50 dark:bg-slate-800/50 border-gray-200 dark:border-slate-700",
};

export default function AdminDashboardPage() {
    const router = useRouter();
    const { user } = useAuthStore();
    const [stats, setStats] = useState<AdminStats | null>(null);
    const [health, setHealth] = useState<HealthResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [healthLoading, setHealthLoading] = useState(true);
    const [flushingCache, setFlushingCache] = useState(false);
    const [togglingMistral, setTogglingMistral] = useState(false);

    // Redirect non-admins
    useEffect(() => {
        if (user && user.role !== "admin") {
            router.replace("/dashboard");
        }
    }, [user, router]);

    useEffect(() => {
        adminAPI.getStats()
            .then(setStats)
            .catch(() => toast.error("Failed to load admin stats"))
            .finally(() => setLoading(false));

        adminAPI.health()
            .then(setHealth)
            .catch(() => { })
            .finally(() => setHealthLoading(false));
    }, []);

    const handleFlushCache = async () => {
        setFlushingCache(true);
        try {
            const res = await adminAPI.flushCache("all");
            toast.success(`Cache flushed — ${res.flushed_keys} keys cleared`);
        } catch {
            toast.error("Failed to flush cache");
        } finally {
            setFlushingCache(false);
        }
    };

    const handleToggleMistral = async () => {
        if (!health) return;
        setTogglingMistral(true);
        try {
            const res = await adminAPI.toggleMistralFallback(!health.mistral_fallback_active);
            setHealth((prev) => prev ? { ...prev, mistral_fallback_active: res.mistral_fallback_active } : prev);
            toast.success(res.message);
        } catch {
            toast.error("Failed to toggle Mistral fallback");
        } finally {
            setTogglingMistral(false);
        }
    };

    if (user?.role !== "admin") return null;

    const roleChartData = stats?.users_by_role.map((r) => ({
        name: ROLE_LABELS[r.role] || r.role,
        value: r.count,
        color: ROLE_COLORS[r.role] || "#94a3b8",
    })) || [];

    const STAT_CARDS = [
        {
            label: "Total Users",
            value: stats?.total_users ?? "—",
            icon: "group",
            color: "text-blue-500",
            bg: "bg-blue-50 dark:bg-blue-500/10",
            border: "border-blue-100 dark:border-blue-500/20",
        },
        {
            label: "Active Users",
            value: stats?.active_users ?? "—",
            icon: "person_check",
            color: "text-emerald-500",
            bg: "bg-emerald-50 dark:bg-emerald-500/10",
            border: "border-emerald-100 dark:border-emerald-500/20",
        },
        {
            label: "Queries Today",
            value: stats?.total_queries_today ?? "—",
            icon: "forum",
            color: "text-purple-500",
            bg: "bg-purple-50 dark:bg-purple-500/10",
            border: "border-purple-100 dark:border-purple-500/20",
        },
        {
            label: "All-Time Queries",
            value: stats?.total_queries_all_time ?? "—",
            icon: "query_stats",
            color: "text-primary",
            bg: "bg-primary/5",
            border: "border-primary/10",
        },
        {
            label: "Total Drafts",
            value: stats?.total_drafts ?? "—",
            icon: "edit_note",
            color: "text-sky-500",
            bg: "bg-sky-50 dark:bg-sky-500/10",
            border: "border-sky-100 dark:border-sky-500/20",
        },
        {
            label: "New Users (7d)",
            value: stats?.recent_signups_7d ?? "—",
            icon: "person_add",
            color: "text-pink-500",
            bg: "bg-pink-50 dark:bg-pink-500/10",
            border: "border-pink-100 dark:border-pink-500/20",
        },
    ];

    return (
        <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8 min-h-full">
            <div className="max-w-7xl mx-auto space-y-8">

                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-amber-600 flex items-center justify-center shadow-lg shadow-primary/20">
                                <span className="material-symbols-outlined text-white text-[22px]">admin_panel_settings</span>
                            </div>
                            Admin Control Center
                        </h2>
                        <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
                            System-wide monitoring, user management, and role-based access control
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={cn(
                            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold border",
                            health?.status === "healthy"
                                ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20"
                                : health?.status === "degraded"
                                    ? "bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20"
                                    : "bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400 border-gray-200 dark:border-slate-700"
                        )}>
                            <span className={cn(
                                "w-2 h-2 rounded-full",
                                health?.status === "healthy" ? "bg-emerald-500 animate-pulse" :
                                    health?.status === "degraded" ? "bg-amber-500 animate-pulse" : "bg-gray-400"
                            )} />
                            System {health?.status || "..."}
                        </span>
                    </div>
                </div>

                {/* KPI Stats */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                    {STAT_CARDS.map((stat) => (
                        <div
                            key={stat.label}
                            className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-4 hover:border-primary/30 transition-colors shadow-sm"
                        >
                            <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center border mb-3", stat.bg, stat.border)}>
                                <span className={cn("material-symbols-outlined text-[18px]", stat.color)}>{stat.icon}</span>
                            </div>
                            {loading ? (
                                <div className="w-10 h-6 bg-gray-200 dark:bg-slate-800 rounded animate-pulse mb-1" />
                            ) : (
                                <p className="text-xl font-bold text-gray-900 dark:text-white">{stat.value?.toLocaleString()}</p>
                            )}
                            <p className="text-[11px] text-gray-500 dark:text-slate-500 font-medium mt-0.5">{stat.label}</p>
                        </div>
                    ))}
                </div>

                {/* Main Grid: Health + Role Chart + Quick Actions */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                    {/* System Health Panel */}
                    <div className="lg:col-span-2 bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
                        <div className="flex items-center justify-between mb-5">
                            <div>
                                <h3 className="text-sm font-bold text-gray-900 dark:text-white">System Health</h3>
                                <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">Live component status</p>
                            </div>
                            <button
                                onClick={() => {
                                    setHealthLoading(true);
                                    adminAPI.health().then(setHealth).catch(() => { }).finally(() => setHealthLoading(false));
                                }}
                                className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                                title="Refresh health"
                            >
                                <span className={cn("material-symbols-outlined text-[18px]", healthLoading && "animate-spin")}>refresh</span>
                            </button>
                        </div>

                        {healthLoading ? (
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                {[...Array(7)].map((_, i) => (
                                    <div key={i} className="h-[72px] bg-gray-100 dark:bg-slate-800 rounded-lg animate-pulse" />
                                ))}
                            </div>
                        ) : health ? (
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                {Object.entries(health.components).map(([name, comp]) => (
                                    <div
                                        key={name}
                                        className={cn(
                                            "rounded-lg border p-3 transition-all",
                                            STATUS_BG[comp.status] || STATUS_BG.unconfigured
                                        )}
                                    >
                                        <div className="flex items-center gap-2 mb-1.5">
                                            <span className={cn("material-symbols-outlined text-[16px]", STATUS_COLORS[comp.status] || "text-gray-400")}>
                                                {HEALTH_ICONS[name] || "settings"}
                                            </span>
                                            <span className="text-xs font-semibold text-gray-700 dark:text-slate-300 capitalize">
                                                {name.replace(/_/g, " ")}
                                            </span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className={cn("text-[10px] font-bold uppercase tracking-wider", STATUS_COLORS[comp.status] || "text-gray-400")}>
                                                {comp.status}
                                            </span>
                                            {comp.latency_ms != null && (
                                                <span className="text-[10px] text-gray-400 dark:text-slate-600">{comp.latency_ms}ms</span>
                                            )}
                                        </div>
                                        {comp.error && (
                                            <p className="text-[10px] text-red-500 dark:text-red-400 mt-1 truncate" title={comp.error}>{comp.error}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-sm text-gray-400 dark:text-slate-500">Unable to load health data</p>
                        )}
                    </div>

                    {/* Role Distribution */}
                    <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
                        <div className="mb-4">
                            <h3 className="text-sm font-bold text-gray-900 dark:text-white">Role Distribution</h3>
                            <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">Users by role</p>
                        </div>
                        {loading ? (
                            <div className="h-[160px] flex items-center justify-center">
                                <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                            </div>
                        ) : roleChartData.length === 0 ? (
                            <div className="h-[160px] flex flex-col items-center justify-center text-center">
                                <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-4xl">donut_large</span>
                                <p className="text-xs text-gray-400 dark:text-slate-500 mt-2">No data</p>
                            </div>
                        ) : (
                            <>
                                <ResponsiveContainer width="100%" height={160}>
                                    <PieChart>
                                        <Pie
                                            data={roleChartData}
                                            cx="50%"
                                            cy="50%"
                                            innerRadius={45}
                                            outerRadius={70}
                                            paddingAngle={3}
                                            dataKey="value"
                                        >
                                            {roleChartData.map((entry, i) => (
                                                <Cell key={i} fill={entry.color} stroke="none" />
                                            ))}
                                        </Pie>
                                        <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                                    </PieChart>
                                </ResponsiveContainer>
                                <div className="mt-2 space-y-1.5">
                                    {roleChartData.map((d) => (
                                        <div key={d.name} className="flex items-center justify-between text-xs">
                                            <div className="flex items-center gap-1.5">
                                                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: d.color }} />
                                                <span className="text-gray-600 dark:text-slate-400">{d.name}</span>
                                            </div>
                                            <span className="font-semibold text-gray-900 dark:text-white">{d.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>
                </div>

                {/* Quick Actions + Admin Navigation */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                    {/* Quick Actions */}
                    <div className="bg-gradient-to-br from-primary/5 to-amber-50/50 dark:from-primary/10 dark:to-primary/5 rounded-xl border border-primary/20 p-6 shadow-sm">
                        <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-1">Quick Actions</h3>
                        <p className="text-xs text-gray-500 dark:text-slate-400 mb-5">System-wide controls</p>
                        <div className="grid grid-cols-2 gap-3">
                            <button
                                onClick={handleFlushCache}
                                disabled={flushingCache}
                                className="flex flex-col items-center gap-2 bg-white dark:bg-[#0f172a] border border-gray-200 dark:border-slate-800 p-4 rounded-xl text-center hover:border-red-300 dark:hover:border-red-500/30 hover:shadow-md transition-all group disabled:opacity-50"
                            >
                                <div className="w-10 h-10 rounded-xl bg-red-50 dark:bg-red-500/10 flex items-center justify-center group-hover:bg-red-100 dark:group-hover:bg-red-500/20 transition-colors">
                                    <span className="material-symbols-outlined text-red-500 text-[22px]">
                                        {flushingCache ? "hourglass_empty" : "delete_sweep"}
                                    </span>
                                </div>
                                <span className="text-xs font-semibold text-gray-700 dark:text-slate-300">Flush Cache</span>
                            </button>

                            <button
                                onClick={handleToggleMistral}
                                disabled={togglingMistral || !health}
                                className="flex flex-col items-center gap-2 bg-white dark:bg-[#0f172a] border border-gray-200 dark:border-slate-800 p-4 rounded-xl text-center hover:border-purple-300 dark:hover:border-purple-500/30 hover:shadow-md transition-all group disabled:opacity-50"
                            >
                                <div className="w-10 h-10 rounded-xl bg-purple-50 dark:bg-purple-500/10 flex items-center justify-center group-hover:bg-purple-100 dark:group-hover:bg-purple-500/20 transition-colors">
                                    <span className="material-symbols-outlined text-purple-500 text-[22px]">
                                        {health?.mistral_fallback_active ? "toggle_on" : "toggle_off"}
                                    </span>
                                </div>
                                <span className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                                    Mistral {health?.mistral_fallback_active ? "ON" : "OFF"}
                                </span>
                            </button>
                        </div>
                    </div>

                    {/* Admin Navigation */}
                    <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-6 shadow-sm">
                        <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-1">Admin Modules</h3>
                        <p className="text-xs text-gray-500 dark:text-slate-400 mb-5">Manage your platform</p>
                        <div className="grid grid-cols-2 gap-3">
                            <Link
                                href="/admin/users"
                                className="flex flex-col items-center gap-2 bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700 p-4 rounded-xl text-center hover:border-primary/30 hover:shadow-md transition-all group"
                            >
                                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                                    <span className="material-symbols-outlined text-primary text-[22px]">group</span>
                                </div>
                                <span className="text-xs font-semibold text-gray-700 dark:text-slate-300">User Management</span>
                            </Link>

                            <Link
                                href="/admin/activity"
                                className="flex flex-col items-center gap-2 bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700 p-4 rounded-xl text-center hover:border-primary/30 hover:shadow-md transition-all group"
                            >
                                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                                    <span className="material-symbols-outlined text-primary text-[22px]">monitoring</span>
                                </div>
                                <span className="text-xs font-semibold text-gray-700 dark:text-slate-300">Activity Log</span>
                            </Link>
                        </div>
                    </div>
                </div>

                {/* Indexed Sections (from health) */}
                {health?.indexed_sections && Object.keys(health.indexed_sections).length > 0 && (
                    <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-5 shadow-sm">
                        <h3 className="text-sm font-bold text-gray-900 dark:text-white mb-4">Indexed Legal Sections</h3>
                        <div className="flex flex-wrap gap-3">
                            {Object.entries(health.indexed_sections).map(([act, count]) => (
                                <div
                                    key={act}
                                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700"
                                >
                                    <span className="material-symbols-outlined text-primary text-[16px]">balance</span>
                                    <span className="text-xs font-semibold text-gray-700 dark:text-slate-300">{act}</span>
                                    <span className="text-xs text-gray-400 dark:text-slate-500">({count.toLocaleString()} sections)</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
