"use client";

import { useState } from "react";
import { useTheme } from "next-themes";
import { useAuthStore } from "@/store/auth";
import { useUIStore, LANGUAGES } from "@/store/ui";
import { useTranslations } from "@/lib/i18n";
import { getRoleLabel, cn } from "@/lib/utils";
import toast from "react-hot-toast";

export default function SettingsPage() {
  const { user } = useAuthStore();
  const { theme, setTheme } = useTheme();
  const { selectedLanguage, setLanguage } = useUIStore();
  const t = useTranslations(selectedLanguage);

  const [includePrecedents, setIncludePrecedents] = useState(false);
  const [voiceOverEnabled, setVoiceOverEnabled] = useState(false);
  const [autoTranslate, setAutoTranslate] = useState(true);

  if (!user) return null;

  const isDark = theme === "dark";

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">Configure your preferences</p>
        </div>

        <div className="space-y-6">

          {/* Appearance */}
          <div className="rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">palette</span>
                Appearance
              </h3>
            </div>
            <div className="p-6 space-y-5">
              {/* Theme */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Theme</p>
                  <p className="text-xs text-gray-500 dark:text-slate-400">Choose between light and dark mode</p>
                </div>
                <div className="flex items-center gap-1 p-1 rounded-lg border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800">
                  {(["light", "dark", "system"] as const).map((mode) => (
                    <button
                      key={mode}
                      onClick={() => setTheme(mode)}
                      className={cn(
                        "px-3 py-1.5 rounded-md text-xs font-medium transition-all capitalize",
                        theme === mode
                          ? "bg-primary text-white shadow-sm"
                          : "text-gray-600 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
                      )}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Language */}
          <div className="rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">language</span>
                Language
              </h3>
            </div>
            <div className="p-6 space-y-5">
              {/* Language Selection */}
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">Interface Language</p>
                <p className="text-xs text-gray-500 dark:text-slate-400 mb-3">Responses will be translated to your selected language</p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {LANGUAGES.map((lang) => (
                    <button
                      key={lang.code}
                      onClick={() => setLanguage(lang.code)}
                      className={cn(
                        "flex items-center justify-between px-3 py-2.5 rounded-lg border text-sm transition-all",
                        selectedLanguage === lang.code
                          ? "border-primary bg-primary/10 text-primary font-semibold"
                          : "border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-300 hover:border-primary/30 hover:bg-primary/5"
                      )}
                    >
                      <span>{lang.label}</span>
                      <span className="text-xs text-gray-400 dark:text-slate-500">{lang.nativeName}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Auto-translate toggle */}
              <ToggleSetting
                label="Auto-translate responses"
                description="Automatically translate AI responses to your selected language"
                enabled={autoTranslate}
                onChange={setAutoTranslate}
              />
            </div>
          </div>

          {/* Query Preferences */}
          <div className="rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">tune</span>
                Query Preferences
              </h3>
            </div>
            <div className="p-6 space-y-5">
              <ToggleSetting
                label="Include precedents by default"
                description="Always search Supreme Court and High Court judgments alongside statutory provisions"
                enabled={includePrecedents}
                onChange={setIncludePrecedents}
              />
              <ToggleSetting
                label="Auto voice-over"
                description="Automatically read responses aloud using text-to-speech"
                enabled={voiceOverEnabled}
                onChange={setVoiceOverEnabled}
              />
            </div>
          </div>

          {/* Account Info */}
          <div className="rounded-2xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-slate-800">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">account_circle</span>
                Account
              </h3>
            </div>
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">{user.full_name}</p>
                  <p className="text-xs text-gray-500 dark:text-slate-400">{user.email}</p>
                </div>
                <span className={cn(
                  "text-xs font-bold px-3 py-1 rounded-full border",
                  "text-primary bg-primary/10 border-primary/20"
                )}>
                  {getRoleLabel(user.role)}
                </span>
              </div>

              <div className="border-t border-gray-200 dark:border-slate-800 pt-4">
                <p className="text-xs text-gray-400 dark:text-slate-500 mb-3">Danger zone</p>
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={() => toast("Password change not yet implemented", { icon: "🔒" })}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 dark:border-slate-700 text-sm text-gray-700 dark:text-slate-300 hover:border-primary/40 hover:text-primary transition-all"
                  >
                    <span className="material-symbols-outlined text-[16px]">lock</span>
                    Change Password
                  </button>
                  <button
                    onClick={() => toast("Data export not yet implemented", { icon: "📦" })}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 dark:border-slate-700 text-sm text-gray-700 dark:text-slate-300 hover:border-primary/40 hover:text-primary transition-all"
                  >
                    <span className="material-symbols-outlined text-[16px]">download</span>
                    Export My Data
                  </button>
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

// ── Toggle Switch Component ───────────────────────────────────────────
function ToggleSetting({
  label,
  description,
  enabled,
  onChange,
}: {
  label: string;
  description: string;
  enabled: boolean;
  onChange: (val: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
        <p className="text-xs text-gray-500 dark:text-slate-400">{description}</p>
      </div>
      <button
        onClick={() => onChange(!enabled)}
        className={cn(
          "relative w-11 h-6 rounded-full transition-colors flex-shrink-0",
          enabled ? "bg-primary" : "bg-gray-300 dark:bg-slate-600"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow-sm transition-transform",
            enabled && "translate-x-5"
          )}
        />
      </button>
    </div>
  );
}
