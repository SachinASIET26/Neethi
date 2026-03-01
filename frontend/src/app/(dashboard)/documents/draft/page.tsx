"use client";

import { useState, useEffect } from "react";
import { documentsAPI } from "@/lib/api";
import { downloadBlob, cn } from "@/lib/utils";
import type { TemplateInfo, DraftResponse } from "@/types";
import toast from "react-hot-toast";

const STEP_LABELS = ["Select Template", "Fill Details", "Review & Export"];

// Template-specific field configs
const TEMPLATE_FIELDS: Record<string, Array<{ key: string; label: string; placeholder: string; required: boolean; type?: "text" | "textarea" }>> = {
  bail_application: [
    { key: "accused_name", label: "Accused Name", placeholder: "e.g. Ramesh Kumar", required: true },
    { key: "fir_number", label: "FIR Number", placeholder: "e.g. FIR No. 145/2026", required: true },
    { key: "police_station", label: "Police Station", placeholder: "e.g. Bandra (West) Police Station, Mumbai", required: true },
    { key: "offence_sections", label: "Offence Sections", placeholder: "e.g. BNS 103, BNS 101", required: true },
    { key: "grounds", label: "Grounds for Bail", placeholder: "State the grounds for bail application...", required: true, type: "textarea" },
    { key: "surety_details", label: "Surety Details", placeholder: "e.g. Mr. Suresh Kumar, father, permanent resident of Mumbai", required: false },
  ],
  legal_notice: [
    { key: "sender_name", label: "Sender Name", placeholder: "Full name of sender", required: true },
    { key: "receiver_name", label: "Receiver Name", placeholder: "Full name of receiver", required: true },
    { key: "sender_address", label: "Sender Address", placeholder: "Complete address", required: true },
    { key: "receiver_address", label: "Receiver Address", placeholder: "Complete address", required: true },
    { key: "subject", label: "Subject", placeholder: "Legal notice subject", required: true },
    { key: "demand", label: "Demand / Relief Sought", placeholder: "State your demand clearly...", required: true, type: "textarea" },
    { key: "notice_period_days", label: "Notice Period (days)", placeholder: "e.g. 30", required: true },
    { key: "lawyer_name", label: "Lawyer Name", placeholder: "Optional", required: false },
  ],
  fir_complaint: [
    { key: "complainant_name", label: "Complainant Name", placeholder: "Your full name", required: true },
    { key: "complainant_address", label: "Complainant Address", placeholder: "Your complete address", required: true },
    { key: "incident_date", label: "Date of Incident", placeholder: "e.g. 25/02/2026", required: true },
    { key: "incident_location", label: "Location of Incident", placeholder: "Where did it happen?", required: true },
    { key: "accused_details", label: "Accused Details", placeholder: "Known/unknown accused details", required: true },
    { key: "incident_description", label: "Incident Description", placeholder: "Describe what happened in detail...", required: true, type: "textarea" },
    { key: "witnesses", label: "Witnesses", placeholder: "Names and addresses of witnesses", required: false },
  ],
  anticipatory_bail: [
    { key: "accused_name", label: "Accused Name", placeholder: "Full name", required: true },
    { key: "fir_number_or_complaint", label: "FIR/Complaint Reference", placeholder: "FIR No. or Complaint Case No.", required: true },
    { key: "police_station", label: "Police Station", placeholder: "Concerned police station", required: true },
    { key: "anticipated_offence_sections", label: "Anticipated Offence Sections", placeholder: "e.g. BNSS 482, BNS 103", required: true },
    { key: "grounds_for_anticipation", label: "Grounds for Anticipatory Bail", placeholder: "Explain why anticipatory bail is sought...", required: true, type: "textarea" },
    { key: "supporting_case_law", label: "Supporting Case Law", placeholder: "Relevant case citations", required: false },
  ],
  power_of_attorney: [
    { key: "principal_name", label: "Principal Name", placeholder: "Person granting authority", required: true },
    { key: "principal_address", label: "Principal Address", placeholder: "Complete address of principal", required: true },
    { key: "agent_name", label: "Agent/Attorney Name", placeholder: "Person receiving authority", required: true },
    { key: "agent_address", label: "Agent Address", placeholder: "Complete address of agent", required: true },
    { key: "powers_granted", label: "Powers Granted", placeholder: "List the specific powers being granted...", required: true, type: "textarea" },
    { key: "effective_date", label: "Effective Date", placeholder: "e.g. 27/02/2026", required: true },
  ],
};

const TEMPLATE_ICONS: Record<string, string> = {
  bail_application: "gavel",
  legal_notice: "mail",
  fir_complaint: "report",
  anticipatory_bail: "security",
  power_of_attorney: "assignment_ind",
};

export default function DraftingWizardPage() {
  const [step, setStep] = useState(1);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateInfo | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<DraftResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [includeCitations, setIncludeCitations] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    documentsAPI
      .listTemplates()
      .then((data) => setTemplates(data.templates))
      .catch(() => toast.error("Failed to load templates"))
      .finally(() => setLoadingTemplates(false));
  }, []);

  const fieldConfig = selectedTemplate ? (TEMPLATE_FIELDS[selectedTemplate.template_id] || []) : [];

  const validateFields = () => {
    const errs: Record<string, string> = {};
    fieldConfig.forEach((f) => {
      if (f.required && !fields[f.key]?.trim()) {
        errs[f.key] = `${f.label} is required`;
      }
    });
    return errs;
  };

  const handleGenerate = async () => {
    const errs = validateFields();
    if (Object.keys(errs).length) { setErrors(errs); return; }

    if (!selectedTemplate) return;
    setLoading(true);
    try {
      const data = await documentsAPI.createDraft({
        template_id: selectedTemplate.template_id,
        fields,
        language: "en",
        include_citations: includeCitations,
      });
      setDraft(data);
      setStep(3);
      toast.success("Draft generated successfully!");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to generate draft.";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleExportPDF = async () => {
    if (!draft) return;
    setExporting(true);
    try {
      const blob = await documentsAPI.exportPDF(draft.draft_id);
      downloadBlob(blob, `${draft.title.replace(/\s+/g, "_")}.pdf`);
      toast.success("PDF exported successfully!");
    } catch {
      toast.error("PDF export failed. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  const setField = (key: string, value: string) => {
    setFields((p) => ({ ...p, [key]: value }));
    if (errors[key]) setErrors((p) => ({ ...p, [key]: "" }));
  };

  return (
    <div className="flex flex-col md:flex-row h-full overflow-hidden">

      {/* Left Pane: Wizard */}
      <aside className="w-full md:w-1/2 lg:w-[460px] flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-200 dark:border-slate-800 bg-white dark:bg-[#020617] flex flex-col overflow-y-auto custom-scrollbar max-h-[60vh] md:max-h-none">
        <div className="p-6 flex-1">
          {/* Header */}
          <div className="mb-7">
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">Drafting Wizard</h1>
            {draft ? (
              <p className="text-gray-500 dark:text-slate-400 text-sm mt-0.5">Draft ID: {draft.draft_id}</p>
            ) : (
              <p className="text-gray-500 dark:text-slate-400 text-sm mt-0.5">Generate legally formatted documents with AI assistance</p>
            )}
          </div>

          {/* Stepper */}
          <div className="flex items-center justify-between mb-8 relative">
            <div className="absolute top-4 left-0 w-full h-0.5 bg-gray-200 dark:bg-slate-800 z-0" />
            {STEP_LABELS.map((label, i) => {
              const s = i + 1;
              const isDone = s < step;
              const isActive = s === step;
              return (
                <div key={label} className="relative z-10 flex flex-col items-center gap-1.5">
                  <div
                    className={cn(
                      "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ring-4 ring-white dark:ring-[#020617]",
                      isDone ? "bg-primary text-white" :
                      isActive ? "bg-primary text-white ring-primary/20" :
                      "bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-400 dark:text-slate-500"
                    )}
                  >
                    {isDone ? (
                      <span className="material-symbols-outlined text-[16px]">check</span>
                    ) : s}
                  </div>
                  <span className={cn("text-[11px] font-medium", isActive ? "text-primary font-bold" : isDone ? "text-gray-400 dark:text-slate-400" : "text-gray-300 dark:text-slate-600")}>
                    {label}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Step 1: Template Selection */}
          {step === 1 && (
            <div className="space-y-3 animate-fade-in">
              <p className="text-sm text-gray-500 dark:text-slate-400 mb-4">Choose a document template to get started.</p>
              {loadingTemplates ? (
                <div className="flex justify-center py-8">
                  <svg className="animate-spin h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                </div>
              ) : (
                templates.map((t) => (
                  <button
                    key={t.template_id}
                    onClick={() => {
                      setSelectedTemplate(t);
                      setFields({});
                      setErrors({});
                    }}
                    className={cn(
                      "w-full flex items-start gap-3.5 p-4 rounded-xl border text-left transition-all",
                      selectedTemplate?.template_id === t.template_id
                        ? "border-primary/50 bg-primary/10"
                        : "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-gray-300 dark:hover:border-slate-600"
                    )}
                  >
                    <div className={cn(
                      "w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0",
                      selectedTemplate?.template_id === t.template_id ? "bg-primary/20" : "bg-gray-100 dark:bg-slate-800"
                    )}>
                      <span className={cn(
                        "material-symbols-outlined text-[20px]",
                        selectedTemplate?.template_id === t.template_id ? "text-primary" : "text-gray-400 dark:text-slate-400"
                      )}>
                        {TEMPLATE_ICONS[t.template_id] || "description"}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={cn("text-sm font-semibold", selectedTemplate?.template_id === t.template_id ? "text-white" : "text-gray-800 dark:text-slate-200")}>
                        {t.template_name}
                      </p>
                      <p className="text-xs text-gray-500 dark:text-slate-500 mt-0.5 leading-relaxed">{t.description}</p>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {t.access_roles.map((r) => (
                          <span key={r} className="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-500">
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>
                    {selectedTemplate?.template_id === t.template_id && (
                      <span className="material-symbols-outlined text-primary text-[20px] flex-shrink-0">check_circle</span>
                    )}
                  </button>
                ))
              )}

              <div className="pt-4 flex justify-end">
                <button
                  onClick={() => { if (selectedTemplate) setStep(2); else toast.error("Please select a template."); }}
                  disabled={!selectedTemplate}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-primary text-white font-bold text-sm shadow-md shadow-primary/20 hover:bg-amber-600 hover:translate-x-0.5 transition-all disabled:opacity-40 disabled:pointer-events-none"
                >
                  Continue
                  <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Fill Details */}
          {step === 2 && selectedTemplate && (
            <div className="space-y-5 animate-fade-in">
              <div className="flex items-center gap-2 mb-2">
                <span className={cn("material-symbols-outlined text-primary text-[20px]")}>
                  {TEMPLATE_ICONS[selectedTemplate.template_id] || "description"}
                </span>
                <h3 className="text-base font-semibold text-gray-900 dark:text-white">{selectedTemplate.template_name}</h3>
              </div>

              {fieldConfig.map((f) => (
                <div key={f.key} className="space-y-1.5">
                  <label className="text-sm font-medium text-gray-700 dark:text-slate-300">
                    {f.label}
                    {f.required && <span className="text-primary ml-1">*</span>}
                  </label>
                  {f.type === "textarea" ? (
                    <textarea
                      value={fields[f.key] || ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      placeholder={f.placeholder}
                      rows={3}
                      className={cn(
                        "w-full px-4 py-2.5 rounded-lg border bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-slate-100 text-sm placeholder-gray-400 dark:placeholder-slate-600 focus:outline-none focus:ring-2 transition-colors resize-none",
                        errors[f.key]
                          ? "border-red-500 focus:ring-red-500/30"
                          : "border-gray-200 dark:border-slate-700 focus:ring-primary/30 focus:border-primary/50"
                      )}
                    />
                  ) : (
                    <input
                      type="text"
                      value={fields[f.key] || ""}
                      onChange={(e) => setField(f.key, e.target.value)}
                      placeholder={f.placeholder}
                      className={cn(
                        "w-full px-4 py-2.5 h-10 rounded-lg border bg-gray-50 dark:bg-slate-900 text-gray-900 dark:text-slate-100 text-sm placeholder-gray-400 dark:placeholder-slate-600 focus:outline-none focus:ring-2 transition-colors",
                        errors[f.key]
                          ? "border-red-500 focus:ring-red-500/30"
                          : "border-gray-200 dark:border-slate-700 focus:ring-primary/30 focus:border-primary/50"
                      )}
                    />
                  )}
                  {errors[f.key] && (
                    <p className="text-xs text-red-400">{errors[f.key]}</p>
                  )}
                </div>
              ))}

              {/* Options */}
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeCitations}
                  onChange={(e) => setIncludeCitations(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-primary focus:ring-primary/50"
                />
                <span className="text-sm text-gray-500 dark:text-slate-400">Include verified statutory citations</span>
              </label>

              <div className="flex items-center justify-between pt-4">
                <button
                  onClick={() => setStep(1)}
                  className="text-gray-500 dark:text-slate-500 hover:text-gray-800 dark:hover:text-slate-300 text-sm font-medium transition-colors"
                >
                  ← Back
                </button>
                <button
                  onClick={handleGenerate}
                  disabled={loading}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-primary text-white font-bold text-sm shadow-md shadow-primary/20 hover:bg-amber-600 transition-all disabled:opacity-40 disabled:pointer-events-none"
                >
                  {loading ? (
                    <><svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Generating...</>
                  ) : (
                    <>Generate Draft<span className="material-symbols-outlined text-[18px]">auto_fix_high</span></>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Review */}
          {step === 3 && draft && (
            <div className="space-y-4 animate-fade-in">
              <div className="p-4 rounded-xl border border-emerald-400/20 bg-emerald-400/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-emerald-400 text-[20px]">check_circle</span>
                  <p className="text-sm font-semibold text-emerald-400">Draft Generated Successfully</p>
                </div>
                <p className="text-xs text-gray-500 dark:text-slate-400">{draft.word_count} words · {draft.citations_used.length} citations verified</p>
              </div>

              <div className="space-y-2">
                <p className="text-xs text-gray-500 dark:text-slate-500 uppercase tracking-wider font-medium">Verified Citations</p>
                <div className="flex flex-wrap gap-1.5">
                  {draft.citations_used.map((c, i) => (
                    <span key={i} className="text-xs px-2 py-1 rounded-full border border-emerald-400/20 bg-emerald-400/10 text-emerald-400">
                      <span className="material-symbols-outlined text-[12px] mr-1">verified</span>
                      {c.act_code.split("_")[0]} §{c.section_number}
                    </span>
                  ))}
                </div>
              </div>

              <div className="p-3 rounded-lg bg-amber-400/5 border border-amber-400/20">
                <p className="text-xs text-amber-400 leading-relaxed">
                  <span className="font-bold">⚠ DRAFT ONLY</span> — {draft.disclaimer}
                </p>
              </div>

              <div className="space-y-2 pt-2">
                <button
                  onClick={handleExportPDF}
                  disabled={exporting}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-primary text-white font-bold text-sm hover:bg-amber-600 transition-all disabled:opacity-50"
                >
                  {exporting ? (
                    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                  ) : (
                    <span className="material-symbols-outlined text-[18px]">picture_as_pdf</span>
                  )}
                  Export as PDF
                </button>
                <button
                  onClick={() => { setStep(2); setDraft(null); }}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 font-medium text-sm hover:bg-gray-50 dark:hover:bg-slate-800 transition-all"
                >
                  <span className="material-symbols-outlined text-[18px]">edit</span>
                  Edit Draft
                </button>
                <button
                  onClick={() => { setStep(1); setSelectedTemplate(null); setDraft(null); setFields({}); }}
                  className="w-full text-gray-500 dark:text-slate-500 text-sm hover:text-gray-800 dark:hover:text-slate-300 transition-colors py-1"
                >
                  Start New Draft
                </button>
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* Right Pane: Document Preview */}
      <section className="flex-1 bg-gray-50 dark:bg-slate-900/50 overflow-y-auto custom-scrollbar p-6 lg:p-10 flex justify-center">
        {draft ? (
          <div className="relative w-full max-w-[760px] min-h-[1050px] h-fit bg-white text-[#1a1a1a] p-14 lg:p-16 shadow-2xl font-serif leading-relaxed mb-16">
            {/* Watermark */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-[0.025] select-none overflow-hidden">
              <span className="text-[100px] font-bold -rotate-45 whitespace-nowrap text-black uppercase tracking-widest">
                DRAFT ONLY
              </span>
            </div>

            {/* Document title */}
            <div className="text-center mb-10 space-y-1">
              <p className="font-bold uppercase text-base tracking-wide underline underline-offset-4">
                {draft.title}
              </p>
            </div>

            {/* Draft content */}
            <div className="text-sm text-[#1a1a1a] leading-relaxed whitespace-pre-wrap">
              {draft.draft_text}
            </div>

            {/* Footer */}
            <div className="absolute bottom-8 left-0 w-full text-center text-xs text-slate-400 font-sans">
              Generated by Neethi AI · {new Date(draft.created_at).toLocaleDateString("en-IN")} · Page 1
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="relative w-full max-w-[600px] min-h-[700px] bg-white dark:bg-white/5 border border-gray-200 dark:border-slate-800 rounded-xl flex flex-col items-center justify-center p-10">
              {/* Mock document lines */}
              <div className="w-full space-y-3 opacity-30 mb-8">
                <div className="h-3 bg-gray-300 dark:bg-slate-700 rounded mx-auto w-2/3" />
                <div className="h-2 bg-gray-200 dark:bg-slate-800 rounded mx-auto w-1/2" />
                <div className="h-2 bg-gray-200 dark:bg-slate-800 rounded mx-auto w-3/4" />
                <div className="mt-6 space-y-2">
                  {[...Array(8)].map((_, i) => (
                    <div key={i} className="h-2 bg-gray-200 dark:bg-slate-800 rounded" style={{ width: `${70 + Math.random() * 25}%` }} />
                  ))}
                </div>
              </div>

              <div className="w-14 h-14 rounded-2xl bg-gray-100 dark:bg-slate-800 flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-gray-400 dark:text-slate-500 text-3xl">description</span>
              </div>
              <p className="text-gray-500 dark:text-slate-400 text-sm font-medium">Document preview will appear here</p>
              <p className="text-gray-400 dark:text-slate-600 text-xs mt-1">Select a template and fill in the details to generate your draft</p>
            </div>
          </div>
        )}

        {/* Floating toolbar */}
        {draft && (
          <div className="fixed bottom-6 right-6 flex flex-col gap-2">
            {[
              { icon: "zoom_in", title: "Zoom In" },
              { icon: "zoom_out", title: "Zoom Out" },
              { icon: "print", title: "Print" },
            ].map((b) => (
              <button
                key={b.icon}
                title={b.title}
                className="w-10 h-10 rounded-full bg-white/90 dark:bg-slate-800/90 border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:bg-primary hover:text-white hover:border-primary transition-all shadow-xl flex items-center justify-center"
              >
                <span className="material-symbols-outlined text-[20px]">{b.icon}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
