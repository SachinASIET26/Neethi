"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useAuthStore } from "@/store/auth";
import { useUIStore, LANGUAGES } from "@/store/ui";

import { authAPI } from "@/lib/api";
import { getRoleLabel, getRoleColor, cn } from "@/lib/utils";

export default function Header() {
  const router = useRouter();
  const { user, clearAuth } = useAuthStore();
  const { theme, setTheme } = useTheme();
  const { selectedLanguage, setLanguage, toggleMobileSidebar } = useUIStore();
  const [showDropdown, setShowDropdown] = useState(false);
  const [showLangDropdown, setShowLangDropdown] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const isDark = theme === "dark";

  const handleLogout = async () => {
    try {
      await authAPI.logout();
    } catch {
      // ignore
    } finally {
      clearAuth();
      router.replace("/login");
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/query?q=${encodeURIComponent(searchQuery.trim())}`);
      setSearchQuery("");
    }
  };

  const initials = user?.full_name
    ?.split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("")
    .toUpperCase() || "NA";

  const currentLang = LANGUAGES.find((l) => l.code === selectedLanguage) || LANGUAGES[0];

  return (
    <header className="h-16 flex-shrink-0 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-[#020617] flex items-center gap-2 px-3 md:px-5">
      {/* Hamburger — mobile only */}
      <button
        onClick={toggleMobileSidebar}
        className="md:hidden p-2 rounded-lg text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors flex-shrink-0"
        aria-label="Open menu"
      >
        <span className="material-symbols-outlined text-[22px]">menu</span>
      </button>

      {/* Search */}
      <form onSubmit={handleSearch} className="flex-1 max-w-xs sm:max-w-md">
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500 text-[18px]">
            search
          </span>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search laws, cases, sections..."
            className="w-full pl-9 pr-4 py-2 h-9 rounded-lg bg-gray-100 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 text-sm text-gray-800 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
          />
        </div>
      </form>

      {/* Actions */}
      <div className="flex items-center gap-1.5 ml-auto">
        {/* Language Selector */}
        <div className="relative">
          <button
            onClick={() => {
              setShowLangDropdown(!showLangDropdown);
              setShowDropdown(false);
            }}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-slate-700"
            title="Select language"
          >
            <span className="material-symbols-outlined text-[16px]">language</span>
            <span className="hidden sm:inline">{currentLang.nativeName}</span>
            <span className="material-symbols-outlined text-[14px]">expand_more</span>
          </button>

          {showLangDropdown && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowLangDropdown(false)} />
              <div className="absolute right-0 top-full mt-1 w-52 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-xl shadow-xl z-20 py-1 animate-fade-in overflow-hidden">
                <p className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400 dark:text-slate-500">
                  Select Language
                </p>
                {LANGUAGES.map((lang) => (
                  <button
                    key={lang.code}
                    onClick={() => {
                      setLanguage(lang.code);
                      setShowLangDropdown(false);
                    }}
                    className={cn(
                      "w-full flex items-center justify-between px-3 py-2 text-sm transition-colors",
                      selectedLanguage === lang.code
                        ? "bg-primary/10 text-primary font-semibold"
                        : "text-gray-700 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white"
                    )}
                  >
                    <span>{lang.label}</span>
                    <span className="text-xs text-gray-400 dark:text-slate-500">{lang.nativeName}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Theme Toggle */}
        <button
          onClick={() => setTheme(isDark ? "light" : "dark")}
          className="p-2 rounded-lg text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white transition-colors"
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          <span className="material-symbols-outlined text-[20px]">
            {isDark ? "light_mode" : "dark_mode"}
          </span>
        </button>

        {/* Notifications */}
        <button className="relative p-2 rounded-lg text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-white transition-colors">
          <span className="material-symbols-outlined text-[20px]">notifications</span>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border-2 border-white dark:border-[#020617]" />
        </button>

        {/* New Query */}
        <Link
          href="/query"
          className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-xs font-bold hover:bg-amber-600 transition-colors"
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
          New Query
        </Link>

        {/* User Profile */}
        <div className="relative">
          <button
            onClick={() => {
              setShowDropdown(!showDropdown);
              setShowLangDropdown(false);
            }}
            className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center flex-shrink-0">
              <span className="text-xs font-bold text-primary">{initials}</span>
            </div>
            <div className="hidden md:block text-left">
              <p className="text-xs font-semibold text-gray-900 dark:text-white leading-tight truncate max-w-[120px]">
                {user?.full_name}
              </p>
              <p className="text-[10px] text-gray-500 dark:text-slate-500 capitalize">
                {user?.role ? getRoleLabel(user.role) : ""}
              </p>
            </div>
            <span className="material-symbols-outlined text-gray-400 dark:text-slate-500 text-[16px]">
              expand_more
            </span>
          </button>

          {showDropdown && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowDropdown(false)} />
              <div className="absolute right-0 top-full mt-1 w-56 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-xl shadow-xl z-20 py-1 animate-fade-in">
                <div className="px-3 py-2.5 border-b border-gray-100 dark:border-slate-800">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">{user?.full_name}</p>
                  <p className="text-xs text-gray-500 dark:text-slate-500">{user?.email}</p>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border mt-1.5",
                      getRoleColor(user?.role || "citizen")
                    )}
                  >
                    {getRoleLabel(user?.role || "citizen")}
                  </span>
                </div>

                <div className="py-1">
                  <Link
                    href="/profile"
                    onClick={() => setShowDropdown(false)}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-slate-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">person</span>
                    My Profile
                  </Link>
                  <Link
                    href="/settings"
                    onClick={() => setShowDropdown(false)}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-slate-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">settings</span>
                    Settings
                  </Link>
                  <button
                    onClick={() => { setTheme(isDark ? "light" : "dark"); setShowDropdown(false); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-slate-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">
                      {isDark ? "light_mode" : "dark_mode"}
                    </span>
                    {isDark ? "Light Mode" : "Dark Mode"}
                  </button>
                </div>

                <div className="border-t border-gray-100 dark:border-slate-800 pt-1">
                  <button
                    onClick={handleLogout}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-slate-800 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[18px]">logout</span>
                    Sign Out
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
