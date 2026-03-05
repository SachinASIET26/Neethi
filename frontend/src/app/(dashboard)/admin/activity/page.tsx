"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { adminAPI } from "@/lib/api";
import { cn, formatDateTime, getRoleLabel, getRoleColor } from "@/lib/utils";
import type { ActivityItem, UserRole } from "@/types";
import toast from "react-hot-toast";

const STATUS_BADGE: Record<string, string> = {
    VERIFIED: "bg-emerald-50 dark:bg-emerald-400/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-400/20",
    PARTIALLY_VERIFIED: "bg-amber-50  dark:bg-amber-400/10  text-amber-600  dark:text-amber-400  border-amber-200  dark:border-amber-400/20",
    UNVERIFIED: "bg-red-50    dark:bg-red-400/10    text-red-600    dark:text-red-400    border-red-200    dark:border-red-400/20",
};

export default function AdminActivityPage() {
    const router = useRouter();
    const { user } = useAuthStore();
    const [activities, setActivities] = useState<ActivityItem[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [roleFilter, setRoleFilter] = useState("");
    const [page, setPage] = useState(0);
    const limit = 20;

    useEffect(() => {
        if (user && user.role !== "admin") router.replace("/dashboard");
    }, [user, router]);

    const fetchActivity = useCallback(async () => {
        setLoading(true);
        try {
            const params: Record<string, unknown> = { limit, offset: page * limit };
            if (roleFilter) params.role = roleFilter;
            const res = await adminAPI.getActivity(params as Parameters<typeof adminAPI.getActivity>[0]);
            setActivities(res.activities);
            setTotal(res.total);
        } catch {
            toast.error("Failed to load activity");
        } finally {
            setLoading(false);
        }
    }, [roleFilter, page]);

    useEffect(() => { fetchActivity(); }, [fetchActivity]);

    if (user?.role !== "admin") return null;

    const totalPages = Math.ceil(total / limit);

    return (
        <div className="p-4 sm:p-6 lg:p-8 min-h-full">
            <div className="max-w-7xl mx-auto space-y-6">

                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center shadow-lg shadow-purple-500/20">
                                <span className="material-symbols-outlined text-white text-[22px]">monitoring</span>
                            </div>
                            Activity Log
                        </h2>
                        <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
                            {total.toLocaleString()} total queries — system-wide query activity
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <select
                            value={roleFilter}
                            onChange={(e) => { setRoleFilter(e.target.value); setPage(0); }}
                            className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-xs font-medium text-gray-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary/20"
                        >
                            <option value="">All Roles</option>
                            <option value="citizen">Citizen</option>
                            <option value="lawyer">Lawyer</option>
                            <option value="legal_advisor">Legal Advisor</option>
                            <option value="police">Police</option>
                            <option value="admin">Admin</option>
                        </select>
                        <button
                            onClick={() => router.push("/admin")}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-600 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                        >
                            <span className="material-symbols-outlined text-[14px]">arrow_back</span>
                            Back
                        </button>
                    </div>
                </div>

                {/* Activity List */}
                <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
                    {loading ? (
                        <div className="p-8 flex justify-center">
                            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : activities.length === 0 ? (
                        <div className="p-10 text-center">
                            <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-5xl">forum</span>
                            <p className="text-gray-400 dark:text-slate-500 text-sm mt-2">No activity found</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-gray-100 dark:divide-slate-800">
                            {activities.map((a) => (
                                <div key={a.query_id} className="px-5 py-4 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors">
                                    <div className="flex items-start gap-4">
                                        {/* Icon */}
                                        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                                            <span className="material-symbols-outlined text-primary text-[18px]">forum</span>
                                        </div>

                                        {/* Content */}
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm text-gray-800 dark:text-slate-200 line-clamp-2">{a.query_text}</p>
                                            <div className="flex flex-wrap items-center gap-2 mt-2">
                                                {/* User info */}
                                                <span className="inline-flex items-center gap-1 text-[10px] text-gray-500 dark:text-slate-500">
                                                    <span className="material-symbols-outlined text-[12px]">person</span>
                                                    {a.user_name}
                                                </span>
                                                <span className="text-gray-300 dark:text-slate-700">·</span>
                                                {/* Role */}
                                                <span className={cn(
                                                    "text-[9px] font-bold px-1.5 py-0.5 rounded-full border uppercase tracking-wide",
                                                    getRoleColor(a.user_role as UserRole)
                                                )}>
                                                    {getRoleLabel(a.user_role as UserRole)}
                                                </span>
                                                <span className="text-gray-300 dark:text-slate-700">·</span>
                                                {/* Time */}
                                                <span className="text-[10px] text-gray-400 dark:text-slate-500">
                                                    {a.created_at ? formatDateTime(a.created_at) : "—"}
                                                </span>
                                                {/* Latency */}
                                                {a.processing_time_ms != null && (
                                                    <>
                                                        <span className="text-gray-300 dark:text-slate-700">·</span>
                                                        <span className="text-[10px] text-gray-400 dark:text-slate-500">
                                                            {a.processing_time_ms.toLocaleString()}ms
                                                        </span>
                                                    </>
                                                )}
                                                {a.cached && (
                                                    <>
                                                        <span className="text-gray-300 dark:text-slate-700">·</span>
                                                        <span className="text-[10px] text-blue-500 font-semibold">CACHED</span>
                                                    </>
                                                )}
                                            </div>
                                        </div>

                                        {/* Status badge */}
                                        <span className={cn(
                                            "text-[9px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 mt-1",
                                            STATUS_BADGE[a.verification_status || "UNVERIFIED"] || STATUS_BADGE.UNVERIFIED
                                        )}>
                                            {a.verification_status === "VERIFIED" ? "Verified" :
                                                a.verification_status === "PARTIALLY_VERIFIED" ? "Partial" : "Unverified"}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100 dark:border-slate-800">
                            <p className="text-xs text-gray-400 dark:text-slate-500">
                                Showing {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total}
                            </p>
                            <div className="flex items-center gap-1">
                                <button
                                    onClick={() => setPage(Math.max(0, page - 1))}
                                    disabled={page === 0}
                                    className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-[18px]">chevron_left</span>
                                </button>
                                <span className="text-xs font-medium text-gray-600 dark:text-slate-400 px-2">
                                    {page + 1} / {totalPages}
                                </span>
                                <button
                                    onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                                    disabled={page >= totalPages - 1}
                                    className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-[18px]">chevron_right</span>
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
