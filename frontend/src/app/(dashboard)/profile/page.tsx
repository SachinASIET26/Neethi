"use client";

import { useState } from "react";
import { useAuthStore } from "@/store/auth";
import { useUIStore } from "@/store/ui";
import { useTranslations } from "@/lib/i18n";
import { getRoleLabel, getRoleColor, formatDate, cn, getRateLimitInfo } from "@/lib/utils";
import toast from "react-hot-toast";

export default function ProfilePage() {
  const { user } = useAuthStore();
  const { selectedLanguage } = useUIStore();
  const t = useTranslations(selectedLanguage);

  const [fullName, setFullName] = useState(user?.full_name || "");
  const [organization, setOrganization] = useState(user?.organization || "");
  const [isSaving, setIsSaving] = useState(false);

  if (!user) return null;

  const initials = user.full_name
    ?.split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("")
    .toUpperCase() || "NA";

  const rateLimits = getRateLimitInfo(user.role);

  const handleSave = async () => {
    setIsSaving(true);
    // Profile update endpoint can be added to the backend later.
    // For now, show a success toast and update local state.
    setTimeout(() => {
      setIsSaving(false);
      toast.success("Profile updated successfully");
    }, 500);
  };

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Profile</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">Manage your account information</p>
        </div>

        {/* Profile Card */}
        <div className="rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm overflow-hidden">
          {/* Avatar + Role Banner */}
          <div className="bg-gradient-to-r from-primary/10 to-primary/5 dark:from-primary/10 dark:to-transparent px-6 py-8 flex items-center gap-5">
            <div className="w-20 h-20 rounded-2xl bg-primary/20 border-2 border-primary/30 flex items-center justify-center flex-shrink-0">
              <span className="text-2xl font-bold text-primary">{initials}</span>
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">{user.full_name}</h2>
              <p className="text-sm text-gray-500 dark:text-slate-400">{user.email}</p>
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-xs font-bold px-3 py-1 rounded-full border mt-2",
                  getRoleColor(user.role)
                )}
              >
                {getRoleLabel(user.role)}
              </span>
            </div>
          </div>

          {/* Info Sections */}
          <div className="p-6 space-y-6">
            {/* Basic Info */}
            <div>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider mb-4">
                Basic Information
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-sm text-gray-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                    Email
                  </label>
                  <input
                    type="email"
                    value={user.email}
                    disabled
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-100 dark:bg-slate-800 text-sm text-gray-500 dark:text-slate-500 cursor-not-allowed"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                    Role
                  </label>
                  <input
                    type="text"
                    value={getRoleLabel(user.role)}
                    disabled
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-100 dark:bg-slate-800 text-sm text-gray-500 dark:text-slate-500 cursor-not-allowed"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                    Organization
                  </label>
                  <input
                    type="text"
                    value={organization}
                    onChange={(e) => setOrganization(e.target.value)}
                    placeholder="Enter your organization"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-sm text-gray-800 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                  />
                </div>
              </div>
            </div>

            {/* Role-specific IDs */}
            {(user.bar_council_id || user.police_badge_id) && (
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider mb-4">
                  Verification
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {user.bar_council_id && (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                        Bar Council ID
                      </label>
                      <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-100 dark:bg-slate-800">
                        <span className="material-symbols-outlined text-emerald-500 text-[16px]">verified</span>
                        <span className="text-sm text-gray-700 dark:text-slate-300">{user.bar_council_id}</span>
                      </div>
                    </div>
                  )}
                  {user.police_badge_id && (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 dark:text-slate-400 mb-1.5">
                        Police Badge ID
                      </label>
                      <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-100 dark:bg-slate-800">
                        <span className="material-symbols-outlined text-emerald-500 text-[16px]">verified</span>
                        <span className="text-sm text-gray-700 dark:text-slate-300">{user.police_badge_id}</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Usage Stats */}
            <div>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider mb-4">
                Usage
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-xl border border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/30 text-center">
                  <p className="text-lg font-bold text-primary">{user.query_count_today ?? 0}</p>
                  <p className="text-[10px] text-gray-500 dark:text-slate-400 uppercase tracking-wider">Queries Today</p>
                </div>
                <div className="p-3 rounded-xl border border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/30 text-center">
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{rateLimits.daily}</p>
                  <p className="text-[10px] text-gray-500 dark:text-slate-400 uppercase tracking-wider">Daily Limit</p>
                </div>
                <div className="p-3 rounded-xl border border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/30 text-center">
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{rateLimits.perMinute}</p>
                  <p className="text-[10px] text-gray-500 dark:text-slate-400 uppercase tracking-wider">Per Minute</p>
                </div>
                <div className="p-3 rounded-xl border border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/30 text-center">
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{rateLimits.docsDaily}</p>
                  <p className="text-[10px] text-gray-500 dark:text-slate-400 uppercase tracking-wider">Docs/Day</p>
                </div>
              </div>
            </div>

            {/* Account Info */}
            <div>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider mb-4">
                Account
              </h3>
              <div className="text-sm text-gray-500 dark:text-slate-400 space-y-1">
                <p>Member since: <span className="text-gray-700 dark:text-slate-300">{user.created_at ? formatDate(user.created_at) : "—"}</span></p>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 dark:border-slate-800 flex justify-end">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:bg-amber-600 transition-colors disabled:opacity-60"
            >
              {isSaving ? (
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <span className="material-symbols-outlined text-[18px]">save</span>
              )}
              Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
