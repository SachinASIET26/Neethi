"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { authAPI } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import toast, { Toaster } from "react-hot-toast";
import type { UserRole } from "@/types";

const ROLES = [
  { value: "citizen", label: "Citizen", icon: "person", desc: "General legal guidance & document drafting" },
  { value: "lawyer", label: "Advocate", icon: "balance", desc: "Full IRAC analysis, case law & precedents" },
  { value: "legal_advisor", label: "Legal Advisor", icon: "business", desc: "Corporate compliance & risk assessment" },
  { value: "police", label: "Police Officer", icon: "local_police", desc: "Criminal law & procedural guidance" },
] as const;

export default function RegisterPage() {
  const router = useRouter();
  const { setAuth } = useAuthStore();

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    role: "citizen" as UserRole,
    bar_council_id: "",
    police_badge_id: "",
    organization: "",
    agreed: false,
  });

  const set = (key: string, value: string | boolean) => {
    setForm((p) => ({ ...p, [key]: value }));
    setErrors((p) => ({ ...p, [key]: "" }));
  };

  const validateStep1 = () => {
    const errs: Record<string, string> = {};
    if (!form.full_name.trim() || form.full_name.trim().length < 2) errs.full_name = "Full name must be at least 2 characters";
    if (!form.email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) errs.email = "Valid email required";
    if (!form.password || form.password.length < 8) errs.password = "Password must be at least 8 characters";
    if (!/[A-Z]/.test(form.password)) errs.password = "Password must contain an uppercase letter";
    if (!/[0-9]/.test(form.password)) errs.password = "Password must contain a number";
    return errs;
  };

  const validateStep2 = () => {
    const errs: Record<string, string> = {};
    if (form.role === "lawyer" && !form.bar_council_id.trim()) errs.bar_council_id = "Bar Council ID required for lawyers";
    if (form.role === "police" && !form.police_badge_id.trim()) errs.police_badge_id = "Badge ID required for police";
    if (!form.agreed) errs.agreed = "You must agree to the Terms of Service";
    return errs;
  };

  const handleNext = () => {
    const errs = validateStep1();
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setStep(2);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateStep2();
    if (Object.keys(errs).length) { setErrors(errs); return; }

    setLoading(true);
    try {
      await authAPI.register({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        password: form.password,
        role: form.role,
        ...(form.role === "lawyer" && { bar_council_id: form.bar_council_id }),
        ...(form.role === "police" && { police_badge_id: form.police_badge_id }),
        ...(form.role === "legal_advisor" && form.organization && { organization: form.organization }),
      });

      // Auto-login
      const loginData = await authAPI.login({ email: form.email.trim(), password: form.password });
      setAuth(loginData.access_token, loginData.user);
      toast.success("Account created! Welcome to Neethi AI.");
      router.replace("/dashboard");
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string }; status?: number }; code?: string; message?: string };
      let msg = "Registration failed. Please try again.";
      if (axiosErr?.code === "ERR_NETWORK" || axiosErr?.message?.includes("Network Error")) {
        msg = "Cannot reach the server. Make sure the backend is running on port 8000.";
      } else if (axiosErr?.response?.status === 409) {
        msg = "An account with this email already exists. Please sign in instead.";
      } else if (axiosErr?.response?.status === 422) {
        msg = axiosErr.response.data?.detail || "Invalid details. Please check your input.";
      } else if (axiosErr?.response?.data?.detail) {
        msg = axiosErr.response.data.detail;
      }
      toast.error(msg, { duration: 5000 });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-950">
      <Toaster
        position="top-right"
        toastOptions={{
          style: { background: "#0f172a", color: "#e2e8f0", border: "1px solid #1e293b", borderRadius: "10px", fontSize: "13px" },
        }}
      />

      {/* Left: Branding */}
      <div className="hidden lg:flex lg:w-1/2 relative bg-slate-900 overflow-hidden">
        {/* Dot pattern */}
        <div
          className="absolute inset-0 z-0 opacity-[0.07]"
          style={{
            backgroundImage: `radial-gradient(circle, #94a3b8 1px, transparent 1px)`,
            backgroundSize: "24px 24px",
          }}
        />
        {/* Blur blobs */}
        <div className="absolute top-1/4 -left-20 w-64 h-64 bg-primary/20 rounded-full blur-3xl z-0" />
        <div className="absolute bottom-1/4 right-10 w-48 h-48 bg-blue-500/10 rounded-full blur-3xl z-0" />

        <div className="absolute inset-0 z-10 bg-gradient-to-tr from-slate-950/90 via-slate-900/50 to-transparent" />

        <div className="relative z-20 flex flex-col justify-between p-12 h-full w-full">
          {/* Logo */}
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-primary rounded-lg">
              <span className="material-symbols-outlined text-white text-2xl">gavel</span>
            </div>
            <span className="text-xl font-black tracking-tight text-white uppercase">Neethi AI</span>
          </div>

          {/* Features */}
          <div className="space-y-6">
            <h2 className="text-3xl font-bold text-white leading-snug">
              One platform for all your <span className="text-primary">legal needs</span>
            </h2>

            {[
              { icon: "verified", label: "Citation-Verified Answers", desc: "Every response is source-cited and verified against the legal database" },
              { icon: "shield", label: "Role-Aware Intelligence", desc: "Tailored responses for citizens, lawyers, advisors & police" },
              { icon: "edit_note", label: "Smart Document Drafting", desc: "Draft bail applications, petitions, legal notices in minutes" },
              { icon: "translate", label: "12 Indian Languages", desc: "Query and receive responses in Hindi, Tamil, Telugu & more" },
            ].map((f) => (
              <div key={f.icon} className="flex items-start gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center mt-0.5">
                  <span className="material-symbols-outlined text-primary text-[18px]">{f.icon}</span>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-200">{f.label}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <p className="text-xs text-slate-600">
            Trusted by 50,000+ legal professionals across India
          </p>
        </div>
      </div>

      {/* Right: Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 overflow-y-auto bg-slate-950">
        {/* Mobile logo */}
        <div className="absolute top-6 left-6 flex lg:hidden items-center gap-2">
          <div className="p-1.5 bg-primary rounded-lg">
            <span className="material-symbols-outlined text-white text-lg">gavel</span>
          </div>
          <span className="text-base font-black text-white uppercase">Neethi AI</span>
        </div>

        <div className="w-full max-w-[440px] space-y-5 mt-14 lg:mt-0">
          {/* Heading */}
          <div>
            <h2 className="text-2xl font-bold text-white">Create your account</h2>
            <p className="text-slate-400 text-sm mt-1">
              Join 50,000+ legal professionals on Neethi AI
            </p>
          </div>

          {/* Step indicator */}
          <div className="flex items-center gap-2">
            {[1, 2].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                    s < step
                      ? "bg-primary text-white"
                      : s === step
                      ? "bg-primary text-white ring-4 ring-primary/20"
                      : "bg-slate-800 text-slate-500 border border-slate-700"
                  }`}
                >
                  {s < step ? (
                    <span className="material-symbols-outlined text-[14px]">check</span>
                  ) : s}
                </div>
                <span className={`text-xs ${s === step ? "text-slate-200 font-medium" : "text-slate-500"}`}>
                  {s === 1 ? "Basic Info" : "Role & Terms"}
                </span>
                {s < 2 && <div className="w-8 h-px bg-slate-800 mx-1" />}
              </div>
            ))}
          </div>

          {/* Step 1 */}
          {step === 1 && (
            <div className="space-y-4 animate-fade-in">
              {/* Full name */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-300">Full Name</label>
                <div className="relative">
                  <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">person</span>
                  <input
                    type="text"
                    value={form.full_name}
                    onChange={(e) => set("full_name", e.target.value)}
                    placeholder="Arjun Sharma"
                    className={`w-full pl-10 pr-4 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${errors.full_name ? "border-red-500 focus:ring-red-500/30" : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"}`}
                  />
                </div>
                {errors.full_name && <p className="text-xs text-red-400">{errors.full_name}</p>}
              </div>

              {/* Email */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-300">Email Address</label>
                <div className="relative">
                  <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">mail</span>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => set("email", e.target.value)}
                    placeholder="arjun@example.com"
                    className={`w-full pl-10 pr-4 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${errors.email ? "border-red-500 focus:ring-red-500/30" : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"}`}
                  />
                </div>
                {errors.email && <p className="text-xs text-red-400">{errors.email}</p>}
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-slate-300">Password</label>
                <div className="relative">
                  <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">lock</span>
                  <input
                    type={showPassword ? "text" : "password"}
                    value={form.password}
                    onChange={(e) => set("password", e.target.value)}
                    placeholder="Min. 8 chars, 1 uppercase, 1 number"
                    className={`w-full pl-10 pr-10 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${errors.password ? "border-red-500 focus:ring-red-500/30" : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"}`}
                  />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                    <span className="material-symbols-outlined text-[20px]">{showPassword ? "visibility_off" : "visibility"}</span>
                  </button>
                </div>
                {errors.password && <p className="text-xs text-red-400">{errors.password}</p>}

                {/* Password strength */}
                {form.password && (
                  <div className="flex gap-1 mt-1.5">
                    {[
                      form.password.length >= 8,
                      /[A-Z]/.test(form.password),
                      /[0-9]/.test(form.password),
                      form.password.length >= 12,
                    ].map((met, i) => (
                      <div key={i} className={`flex-1 h-1 rounded-full transition-colors ${met ? "bg-primary" : "bg-slate-800"}`} />
                    ))}
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={handleNext}
                className="w-full h-11 rounded-lg bg-primary text-white font-semibold text-sm hover:bg-amber-600 active:scale-[0.98] transition-all flex items-center justify-center gap-2"
              >
                Continue
                <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
              </button>
            </div>
          )}

          {/* Step 2 */}
          {step === 2 && (
            <form onSubmit={handleSubmit} className="space-y-4 animate-fade-in">
              {/* Role Selection */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-300">Select Your Role</label>
                <div className="grid grid-cols-2 gap-2">
                  {ROLES.map((r) => (
                    <button
                      key={r.value}
                      type="button"
                      onClick={() => set("role", r.value)}
                      className={`flex flex-col items-start p-3 rounded-lg border text-left transition-all ${
                        form.role === r.value
                          ? "border-primary/50 bg-primary/10 text-white"
                          : "border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-600 hover:text-slate-300"
                      }`}
                    >
                      <span className={`material-symbols-outlined text-[20px] mb-1 ${form.role === r.value ? "text-primary" : ""}`}>{r.icon}</span>
                      <span className="text-xs font-semibold">{r.label}</span>
                      <span className="text-[10px] text-slate-500 mt-0.5 leading-tight">{r.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Conditional fields */}
              {form.role === "lawyer" && (
                <div className="space-y-1.5 animate-fade-in">
                  <label className="text-sm font-medium text-slate-300">Bar Council ID</label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">badge</span>
                    <input
                      type="text"
                      value={form.bar_council_id}
                      onChange={(e) => set("bar_council_id", e.target.value)}
                      placeholder="BAR/MH/2019/12345"
                      className={`w-full pl-10 pr-4 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${errors.bar_council_id ? "border-red-500 focus:ring-red-500/30" : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"}`}
                    />
                  </div>
                  {errors.bar_council_id && <p className="text-xs text-red-400">{errors.bar_council_id}</p>}
                </div>
              )}

              {form.role === "police" && (
                <div className="space-y-1.5 animate-fade-in">
                  <label className="text-sm font-medium text-slate-300">Police Badge ID</label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">fingerprint</span>
                    <input
                      type="text"
                      value={form.police_badge_id}
                      onChange={(e) => set("police_badge_id", e.target.value)}
                      placeholder="PB/MH/2024/001"
                      className={`w-full pl-10 pr-4 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${errors.police_badge_id ? "border-red-500 focus:ring-red-500/30" : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"}`}
                    />
                  </div>
                  {errors.police_badge_id && <p className="text-xs text-red-400">{errors.police_badge_id}</p>}
                </div>
              )}

              {form.role === "legal_advisor" && (
                <div className="space-y-1.5 animate-fade-in">
                  <label className="text-sm font-medium text-slate-300">Organization <span className="text-slate-500">(optional)</span></label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">business</span>
                    <input
                      type="text"
                      value={form.organization}
                      onChange={(e) => set("organization", e.target.value)}
                      placeholder="e.g. Tata Consultancy Services"
                      className="w-full pl-10 pr-4 h-11 rounded-lg border border-slate-700 bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                    />
                  </div>
                </div>
              )}

              {/* Terms */}
              <div className="space-y-1.5">
                <label className="flex items-start gap-2.5 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={form.agreed}
                    onChange={(e) => set("agreed", e.target.checked)}
                    className="w-4 h-4 mt-0.5 rounded border-slate-700 bg-slate-900 text-primary focus:ring-primary/50 cursor-pointer flex-shrink-0"
                  />
                  <span className="text-sm text-slate-400 group-hover:text-slate-300 leading-relaxed transition-colors">
                    I agree to the{" "}
                    <Link href="#" className="text-primary hover:underline">Terms of Service</Link>
                    {" "}and{" "}
                    <Link href="#" className="text-primary hover:underline">Privacy Policy</Link>
                    . Neethi AI is an AI tool and does not provide legal advice.
                  </span>
                </label>
                {errors.agreed && <p className="text-xs text-red-400 ml-6">{errors.agreed}</p>}
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="flex-1 h-11 rounded-lg border border-slate-700 text-slate-300 font-medium text-sm hover:bg-slate-800 hover:text-white transition-all"
                >
                  Back
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 h-11 rounded-lg bg-primary text-white font-semibold text-sm hover:bg-amber-600 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <><svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Creating...</>
                  ) : (
                    <>Create Account<span className="material-symbols-outlined text-[18px]">check</span></>
                  )}
                </button>
              </div>
            </form>
          )}

          <p className="text-center text-sm text-slate-500">
            Already have an account?{" "}
            <Link href="/login" className="text-primary hover:text-amber-500 font-medium transition-colors">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
