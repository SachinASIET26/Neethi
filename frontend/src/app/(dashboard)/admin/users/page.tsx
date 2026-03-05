"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { adminAPI } from "@/lib/api";
import { cn, formatDateTime, getRoleLabel, getRoleColor } from "@/lib/utils";
import type { UserListItem, UserRole } from "@/types";
import toast from "react-hot-toast";

const ALL_ROLES: UserRole[] = ["citizen", "lawyer", "legal_advisor", "police", "admin"];

export default function AdminUsersPage() {
    const router = useRouter();
    const { user } = useAuthStore();
    const [users, setUsers] = useState<UserListItem[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);

    // Filters
    const [search, setSearch] = useState("");
    const [roleFilter, setRoleFilter] = useState<string>("");
    const [activeFilter, setActiveFilter] = useState<string>("");
    const [page, setPage] = useState(0);
    const limit = 20;

    // Detail / edit
    const [editingUserId, setEditingUserId] = useState<string | null>(null);
    const [editRole, setEditRole] = useState<UserRole>("citizen");
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (user && user.role !== "admin") router.replace("/dashboard");
    }, [user, router]);

    const fetchUsers = useCallback(async () => {
        setLoading(true);
        try {
            const params: Record<string, unknown> = { limit, offset: page * limit };
            if (search) params.search = search;
            if (roleFilter) params.role = roleFilter;
            if (activeFilter) params.is_active = activeFilter === "active";
            const res = await adminAPI.listUsers(params as Parameters<typeof adminAPI.listUsers>[0]);
            setUsers(res.users);
            setTotal(res.total);
        } catch {
            toast.error("Failed to load users");
        } finally {
            setLoading(false);
        }
    }, [search, roleFilter, activeFilter, page]);

    useEffect(() => { fetchUsers(); }, [fetchUsers]);

    const handleRoleChange = async (userId: string, newRole: UserRole) => {
        setSaving(true);
        try {
            await adminAPI.updateUser(userId, { role: newRole });
            toast.success("Role updated");
            setEditingUserId(null);
            fetchUsers();
        } catch {
            toast.error("Failed to update role");
        } finally {
            setSaving(false);
        }
    };

    const handleToggleActive = async (u: UserListItem) => {
        try {
            await adminAPI.updateUser(u.user_id, { is_active: !u.is_active });
            toast.success(u.is_active ? "User deactivated" : "User activated");
            fetchUsers();
        } catch {
            toast.error("Failed to update user status");
        }
    };

    if (user?.role !== "admin") return null;

    const totalPages = Math.ceil(total / limit);

    return (
        <div className="p-4 sm:p-6 lg:p-8 min-h-full">
            <div className="max-w-7xl mx-auto space-y-6">

                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
                                <span className="material-symbols-outlined text-white text-[22px]">group</span>
                            </div>
                            User Management
                        </h2>
                        <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
                            {total.toLocaleString()} users total — manage roles and access
                        </p>
                    </div>
                    <button
                        onClick={() => router.push("/admin")}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-600 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors"
                    >
                        <span className="material-symbols-outlined text-[14px]">arrow_back</span>
                        Back to Admin
                    </button>
                </div>

                {/* Filters */}
                <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 p-4 shadow-sm">
                    <div className="flex flex-col sm:flex-row gap-3">
                        <div className="flex-1 relative">
                            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500 text-[18px]">search</span>
                            <input
                                type="text"
                                value={search}
                                onChange={(e) => { setSearch(e.target.value); setPage(0); }}
                                placeholder="Search by name or email..."
                                className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
                            />
                        </div>
                        <select
                            value={roleFilter}
                            onChange={(e) => { setRoleFilter(e.target.value); setPage(0); }}
                            className="px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                        >
                            <option value="">All Roles</option>
                            {ALL_ROLES.map((r) => (
                                <option key={r} value={r}>{getRoleLabel(r)}</option>
                            ))}
                        </select>
                        <select
                            value={activeFilter}
                            onChange={(e) => { setActiveFilter(e.target.value); setPage(0); }}
                            className="px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
                        >
                            <option value="">All Status</option>
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                        </select>
                    </div>
                </div>

                {/* User Table */}
                <div className="bg-white dark:bg-[#0f172a] rounded-xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
                    {loading ? (
                        <div className="p-8 flex justify-center">
                            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        </div>
                    ) : users.length === 0 ? (
                        <div className="p-10 text-center">
                            <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-5xl">person_off</span>
                            <p className="text-gray-400 dark:text-slate-500 text-sm mt-2">No users found</p>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="border-b border-gray-100 dark:border-slate-800">
                                        <th className="text-left text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">User</th>
                                        <th className="text-left text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">Role</th>
                                        <th className="text-left text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">Status</th>
                                        <th className="text-left text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">Queries Today</th>
                                        <th className="text-left text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">Joined</th>
                                        <th className="text-right text-[11px] font-bold text-gray-500 dark:text-slate-500 uppercase tracking-wider px-5 py-3">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
                                    {users.map((u) => (
                                        <tr key={u.user_id} className="hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors">
                                            <td className="px-5 py-3">
                                                <div className="flex items-center gap-3">
                                                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                                                        <span className="material-symbols-outlined text-primary text-[16px]">person</span>
                                                    </div>
                                                    <div className="min-w-0">
                                                        <p className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate">{u.full_name}</p>
                                                        <p className="text-xs text-gray-400 dark:text-slate-500 truncate">{u.email}</p>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-5 py-3">
                                                {editingUserId === u.user_id ? (
                                                    <div className="flex items-center gap-2">
                                                        <select
                                                            value={editRole}
                                                            onChange={(e) => setEditRole(e.target.value as UserRole)}
                                                            className="px-2 py-1 rounded border border-primary/40 bg-white dark:bg-slate-800 text-xs font-medium focus:outline-none"
                                                        >
                                                            {ALL_ROLES.map((r) => (
                                                                <option key={r} value={r}>{getRoleLabel(r)}</option>
                                                            ))}
                                                        </select>
                                                        <button
                                                            onClick={() => handleRoleChange(u.user_id, editRole)}
                                                            disabled={saving}
                                                            className="p-1 rounded text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 transition-colors"
                                                            title="Save"
                                                        >
                                                            <span className="material-symbols-outlined text-[16px]">check</span>
                                                        </button>
                                                        <button
                                                            onClick={() => setEditingUserId(null)}
                                                            className="p-1 rounded text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                                                            title="Cancel"
                                                        >
                                                            <span className="material-symbols-outlined text-[16px]">close</span>
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <span
                                                        className={cn(
                                                            "inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wide cursor-pointer hover:opacity-80 transition-opacity",
                                                            getRoleColor(u.role)
                                                        )}
                                                        onClick={() => { setEditingUserId(u.user_id); setEditRole(u.role); }}
                                                        title="Click to edit role"
                                                    >
                                                        {getRoleLabel(u.role)}
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-5 py-3">
                                                <span className={cn(
                                                    "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wide",
                                                    u.is_active
                                                        ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20"
                                                        : "bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 border-red-200 dark:border-red-500/20"
                                                )}>
                                                    <span className={cn("w-1.5 h-1.5 rounded-full", u.is_active ? "bg-emerald-500" : "bg-red-500")} />
                                                    {u.is_active ? "Active" : "Inactive"}
                                                </span>
                                            </td>
                                            <td className="px-5 py-3">
                                                <span className="text-sm font-medium text-gray-700 dark:text-slate-300">{u.query_count_today}</span>
                                            </td>
                                            <td className="px-5 py-3">
                                                <span className="text-xs text-gray-400 dark:text-slate-500">
                                                    {u.created_at ? formatDateTime(u.created_at) : "—"}
                                                </span>
                                            </td>
                                            <td className="px-5 py-3 text-right">
                                                <button
                                                    onClick={() => handleToggleActive(u)}
                                                    className={cn(
                                                        "inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all",
                                                        u.is_active
                                                            ? "text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
                                                            : "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-500/10"
                                                    )}
                                                    title={u.is_active ? "Deactivate user" : "Activate user"}
                                                >
                                                    <span className="material-symbols-outlined text-[14px]">
                                                        {u.is_active ? "person_off" : "person_check"}
                                                    </span>
                                                    {u.is_active ? "Deactivate" : "Activate"}
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
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
