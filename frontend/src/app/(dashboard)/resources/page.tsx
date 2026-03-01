"use client";

import { useState } from "react";
import { resourcesAPI } from "@/lib/api";
import type { ResourceResult, EligibilityResponse } from "@/types";
import toast from "react-hot-toast";
import { cn } from "@/lib/utils";

type ResourceType = "legal_aid" | "court" | "lawyer" | "police_station" | "notary";

const FILTERS: Array<{ type: ResourceType; label: string; icon: string }> = [
  { type: "legal_aid", label: "Legal Aid", icon: "gavel" },
  { type: "court", label: "Courts", icon: "account_balance" },
  { type: "police_station", label: "Police", icon: "local_police" },
  { type: "notary", label: "Notaries", icon: "assignment" },
  { type: "lawyer", label: "Lawyers", icon: "person" },
];

const CATEGORIES = [
  { value: "general", label: "General" },
  { value: "sc", label: "SC" },
  { value: "st", label: "ST" },
  { value: "woman", label: "Women/Children" },
  { value: "disabled", label: "Disabled" },
];

const STATUS_COLORS: Record<string, string> = {
  legal_aid:       "text-blue-500",
  court:           "text-purple-500",
  police_station:  "text-slate-500",
  notary:          "text-amber-500",
  lawyer:          "text-emerald-500",
};

const RESOURCE_ICONS: Record<ResourceType, string> = {
  legal_aid:      "gavel",
  court:          "account_balance",
  lawyer:         "person",
  police_station: "local_police",
  notary:         "assignment",
};

function StarRating({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <span
          key={s}
          className={cn(
            "material-symbols-outlined text-[14px]",
            s <= Math.round(rating) ? "text-amber-400" : "text-gray-300 dark:text-slate-700"
          )}
        >
          star
        </span>
      ))}
      <span className="text-xs text-gray-400 dark:text-slate-500 ml-1">{rating.toFixed(1)}</span>
    </div>
  );
}

function ResourceCard({ resource, type }: { resource: ResourceResult; type: ResourceType }) {
  return (
    <div className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] hover:border-primary/30 transition-all animate-fade-in shadow-sm">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
          <span className={cn("material-symbols-outlined text-[20px]", STATUS_COLORS[type] || "text-gray-400")}>
            {RESOURCE_ICONS[type]}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">{resource.name}</p>
            {resource.open_now !== undefined && (
              <span className={cn(
                "text-[10px] font-bold px-1.5 py-0.5 rounded border flex-shrink-0",
                resource.open_now
                  ? "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-400/10 border-emerald-200 dark:border-emerald-400/20"
                  : "text-gray-400 dark:text-slate-500 bg-gray-100 dark:bg-slate-800 border-gray-200 dark:border-slate-700"
              )}>
                {resource.open_now ? "Open" : "Closed"}
              </span>
            )}
          </div>

          <p className="text-xs text-gray-500 dark:text-slate-500 mt-1 flex items-start gap-1">
            <span className="material-symbols-outlined text-[13px] flex-shrink-0 mt-0.5">location_on</span>
            {resource.address}
          </p>

          {resource.rating && <div className="mt-1.5"><StarRating rating={resource.rating} /></div>}

          <div className="flex items-center gap-3 mt-2 flex-wrap">
            {resource.distance_km && (
              <span className="text-xs text-gray-500 dark:text-slate-500 flex items-center gap-0.5">
                <span className="material-symbols-outlined text-[13px]">directions</span>
                {resource.distance_km.toFixed(1)} km
              </span>
            )}
            {resource.phone && (
              <a href={`tel:${resource.phone}`} className="text-xs text-primary hover:text-amber-500 transition-colors flex items-center gap-0.5">
                <span className="material-symbols-outlined text-[13px]">call</span>
                {resource.phone}
              </a>
            )}
          </div>

          {resource.services && resource.services.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {resource.services.slice(0, 3).map((s) => (
                <span key={s} className="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-500 bg-gray-50 dark:bg-slate-900">
                  {s}
                </span>
              ))}
            </div>
          )}

          <div className="mt-3 flex gap-2 flex-wrap">
            {resource.maps_url && (
              <a
                href={resource.maps_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-xs text-gray-600 dark:text-slate-300 hover:border-primary/30 hover:text-gray-900 dark:hover:text-white transition-all"
              >
                <span className="material-symbols-outlined text-[14px]">directions</span>
                Directions
              </a>
            )}
            {resource.website && (
              <a
                href={resource.website}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-xs text-gray-600 dark:text-slate-300 hover:border-primary/30 hover:text-gray-900 dark:hover:text-white transition-all"
              >
                <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                Website
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ResourcesPage() {
  const [activeFilter, setActiveFilter] = useState<ResourceType>("legal_aid");
  const [resources, setResources] = useState<ResourceResult[]>([]);
  const [eligibility, setEligibility] = useState<EligibilityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [eligLoading, setEligLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const [city, setCity] = useState("");
  const [state, setState] = useState("all");
  const [annualIncome, setAnnualIncome] = useState("");
  const [category, setCategory] = useState("general");
  const [eligState, setEligState] = useState("all");

  const handleSearch = async () => {
    if (!city.trim()) { toast.error("Please enter a city name."); return; }
    setLoading(true);
    setResources([]);
    try {
      const data = await resourcesAPI.findNearby({ resource_type: activeFilter, city: city.trim(), state: state || "all", limit: 10 });
      setResources(data.results);
      setSearched(true);
      if (data.results.length === 0) toast("No resources found nearby.", { icon: "🔍" });
    } catch {
      toast.error("Search failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleEligibilityCheck = async () => {
    if (!annualIncome || isNaN(Number(annualIncome))) { toast.error("Please enter a valid annual income."); return; }
    setEligLoading(true);
    try {
      const data = await resourcesAPI.checkEligibility(Number(annualIncome), category, eligState);
      setEligibility(data);
    } catch {
      toast.error("Eligibility check failed. Please try again.");
    } finally {
      setEligLoading(false);
    }
  };

  const inputCls = "w-full h-9 px-3 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-800 dark:text-slate-100 text-sm placeholder-gray-400 dark:placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors";

  return (
    <div className="p-4 sm:p-5 lg:p-8 min-h-full">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* Header */}
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">Legal Resources &amp; Aid Hub</h1>
          <p className="text-gray-500 dark:text-slate-400 text-sm mt-1">
            Find nearby courts, legal aid centers, lawyers, and police stations across India.
          </p>
        </div>

        {/* Eligibility Checker */}
        <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] overflow-hidden shadow-sm">
          <div className="px-5 py-4 bg-gradient-to-r from-primary/10 to-transparent border-b border-gray-100 dark:border-slate-800 flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[20px]">shield</span>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Free Legal Aid Eligibility Checker</h2>
          </div>
          <div className="p-4 sm:p-5">
            <p className="text-xs text-gray-500 dark:text-slate-500 mb-4">
              Check your eligibility for free legal aid under the Legal Services Authorities Act, 1987.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-slate-400">Annual Family Income (₹)</label>
                <input type="number" value={annualIncome} onChange={(e) => setAnnualIncome(e.target.value)} placeholder="e.g. 150000" className={inputCls} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-slate-400">Category</label>
                <select value={category} onChange={(e) => setCategory(e.target.value)} className={inputCls + " appearance-none"}>
                  {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-slate-400">State (optional)</label>
                <input type="text" value={eligState} onChange={(e) => setEligState(e.target.value)} placeholder="e.g. MH, DL, TN" className={inputCls} />
              </div>
              <div className="flex items-end">
                <button onClick={handleEligibilityCheck} disabled={eligLoading} className="w-full h-9 flex items-center justify-center gap-1.5 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-amber-600 transition-all disabled:opacity-50">
                  {eligLoading
                    ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    : <><span className="material-symbols-outlined text-[16px]">check_circle</span>Check</>}
                </button>
              </div>
            </div>

            {eligibility && (
              <div className={cn("mt-4 p-4 rounded-xl border animate-fade-in", eligibility.eligible ? "border-emerald-400/20 bg-emerald-50 dark:bg-emerald-400/5" : "border-red-400/20 bg-red-50 dark:bg-red-400/5")}>
                <div className="flex items-start gap-3">
                  <span className={cn("material-symbols-outlined text-[24px] flex-shrink-0", eligibility.eligible ? "text-emerald-500 dark:text-emerald-400" : "text-red-500 dark:text-red-400")}>
                    {eligibility.eligible ? "check_circle" : "cancel"}
                  </span>
                  <div className="flex-1">
                    <p className={cn("text-sm font-bold", eligibility.eligible ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                      {eligibility.eligible ? "You are eligible for free legal aid" : "Not currently eligible"}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">{eligibility.basis}</p>
                    {eligibility.eligible && (
                      <div className="mt-3 space-y-1.5">
                        <p className="text-xs font-medium text-gray-700 dark:text-slate-300">Your entitlements:</p>
                        {eligibility.entitlements.map((e) => (
                          <div key={e} className="flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                            <span className="material-symbols-outlined text-emerald-500 dark:text-emerald-400 text-[14px]">check</span>
                            {e}
                          </div>
                        ))}
                        <div className="mt-2 pt-2 border-t border-gray-200 dark:border-slate-800">
                          <p className="text-xs text-gray-500 dark:text-slate-500">
                            Contact: <span className="text-gray-700 dark:text-slate-300">{eligibility.contact.authority}</span> ·
                            Helpline: <a href={`tel:${eligibility.contact.helpline}`} className="text-primary">{eligibility.contact.helpline}</a>
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Resource Search */}
        <div className="rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] overflow-hidden shadow-sm">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-slate-800 flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[20px]">location_on</span>
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Find Nearby Resources</h2>
          </div>
          <div className="p-4 sm:p-5 space-y-4">
            {/* Search bar */}
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500 text-[18px] pointer-events-none">location_city</span>
                <input
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  placeholder="Enter city (e.g. Mumbai, Delhi)"
                  className="w-full pl-9 pr-4 h-10 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-800 dark:text-slate-100 text-sm placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                />
              </div>
              <input
                type="text"
                value={state === "all" ? "" : state}
                onChange={(e) => setState(e.target.value || "all")}
                placeholder="State"
                className="w-16 sm:w-24 px-2 sm:px-3 h-10 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-800 dark:text-slate-100 text-sm placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/30 transition-colors"
              />
              <button
                onClick={handleSearch}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 sm:px-4 h-10 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-amber-600 transition-all disabled:opacity-50 flex-shrink-0"
              >
                {loading
                  ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  : <span className="material-symbols-outlined text-[18px]">search</span>}
                <span className="hidden sm:inline">Search</span>
              </button>
            </div>

            {/* Filter pills */}
            <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
              {FILTERS.map((f) => (
                <button
                  key={f.type}
                  onClick={() => setActiveFilter(f.type)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs sm:text-sm font-medium whitespace-nowrap transition-all flex-shrink-0",
                    activeFilter === f.type
                      ? "border-primary/50 bg-primary/10 text-primary"
                      : "border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900 text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300 hover:border-gray-300 dark:hover:border-slate-600"
                  )}
                >
                  <span className="material-symbols-outlined text-[16px]">{f.icon}</span>
                  {f.label}
                </button>
              ))}
            </div>

            {/* Results */}
            {loading ? (
              <div className="flex justify-center py-8">
                <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            ) : resources.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {resources.map((r, i) => <ResourceCard key={i} resource={r} type={activeFilter} />)}
              </div>
            ) : searched ? (
              <div className="text-center py-8">
                <span className="material-symbols-outlined text-gray-300 dark:text-slate-700 text-4xl">location_off</span>
                <p className="text-gray-500 dark:text-slate-500 text-sm mt-2">No {FILTERS.find(f => f.type === activeFilter)?.label} found in {city}.</p>
                <p className="text-gray-400 dark:text-slate-600 text-xs mt-1">Try a different city or resource type.</p>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-400 dark:text-slate-600 text-sm">
                Enter a city name to search for nearby legal resources.
              </div>
            )}
          </div>
        </div>

        {/* Info Panel */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { icon: "gavel",         title: "NALSA Scheme",            desc: "Free legal aid for all under the National Legal Services Authority. Income limit: ₹3 lakh/year.", color: "text-blue-500" },
            { icon: "phone_in_talk", title: "Legal Helpline",          desc: "Call 15100 (toll-free) for immediate legal guidance. Available 24/7 across India.", color: "text-emerald-500" },
            { icon: "location_on",   title: "District Legal Services", desc: "Every district has a DLSA. Visit your local court complex for free legal assistance.", color: "text-primary" },
          ].map((info) => (
            <div key={info.title} className="p-4 rounded-xl border border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0f172a] shadow-sm">
              <span className={cn("material-symbols-outlined text-[24px] mb-2 block", info.color)}>{info.icon}</span>
              <p className="text-sm font-semibold text-gray-900 dark:text-white mb-1">{info.title}</p>
              <p className="text-xs text-gray-500 dark:text-slate-500 leading-relaxed">{info.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
