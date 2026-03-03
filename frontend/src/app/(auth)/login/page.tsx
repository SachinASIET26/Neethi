"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { authAPI } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import toast from "react-hot-toast";
import { Toaster } from "react-hot-toast";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect = searchParams.get("redirect") || "/dashboard";
  const { setAuth } = useAuthStore();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});

  const validate = () => {
    const errs: typeof errors = {};
    if (!email.trim()) errs.email = "Email is required";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errs.email = "Invalid email address";
    if (!password) errs.password = "Password is required";
    return errs;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    setErrors({});
    setLoading(true);
    try {
      const data = await authAPI.login({ email: email.trim(), password });
      setAuth(data.access_token, data.user);
      toast.success(`Welcome back, ${data.user.full_name.split(" ")[0]}!`);
      router.replace(redirect);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string }; status?: number }; code?: string; message?: string };
      let msg = "Invalid email or password.";
      if (axiosErr?.code === "ERR_NETWORK" || axiosErr?.message?.includes("Network Error")) {
        msg = "Cannot reach the server. Make sure the backend is running on port 8000.";
      } else if (axiosErr?.response?.status === 401) {
        msg = "Incorrect email or password. Please try again.";
      } else if (axiosErr?.response?.data?.detail) {
        msg = axiosErr.response.data.detail;
      }
      toast.error(msg, { duration: 5000 });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-[420px] space-y-6">
      {/* Heading */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight text-white">Welcome back</h2>
        <p className="text-slate-400 text-sm mt-1.5">
          Enter your credentials to access your legal dashboard
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Email */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-slate-300" htmlFor="email">
            Email address
          </label>
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">
              mail
            </span>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setErrors(p => ({ ...p, email: undefined })); }}
              placeholder="you@example.com"
              className={`w-full pl-10 pr-4 py-2.5 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${
                errors.email
                  ? "border-red-500 focus:ring-red-500/30"
                  : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"
              }`}
            />
          </div>
          {errors.email && (
            <p className="text-xs text-red-400 flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px]">error</span>
              {errors.email}
            </p>
          )}
        </div>

        {/* Password */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-slate-300" htmlFor="password">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-primary hover:text-amber-500 transition-colors"
            >
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[20px] pointer-events-none">
              lock
            </span>
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setErrors(p => ({ ...p, password: undefined })); }}
              placeholder="Enter your password"
              className={`w-full pl-10 pr-10 py-2.5 h-11 rounded-lg border bg-slate-900 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 transition-colors ${
                errors.password
                  ? "border-red-500 focus:ring-red-500/30"
                  : "border-slate-700 focus:ring-primary/30 focus:border-primary/50"
              }`}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">
                {showPassword ? "visibility_off" : "visibility"}
              </span>
            </button>
          </div>
          {errors.password && (
            <p className="text-xs text-red-400 flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px]">error</span>
              {errors.password}
            </p>
          )}
        </div>

        {/* Remember me */}
        <label className="flex items-center gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            className="w-4 h-4 rounded border-slate-700 bg-slate-900 text-primary focus:ring-primary/50 cursor-pointer"
          />
          <span className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
            Remember me for 30 days
          </span>
        </label>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading}
          className="w-full h-11 rounded-lg bg-primary text-white font-semibold text-sm shadow-md shadow-primary/20 hover:bg-amber-600 active:scale-[0.98] transition-all disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Authenticating...
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-[18px]">login</span>
              Sign In
            </>
          )}
        </button>
      </form>

      {/* Sign up link */}
      <p className="text-center text-sm text-slate-500">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-primary hover:text-amber-500 font-medium transition-colors">
          Create account
        </Link>
      </p>

      {/* Footer */}
      <div className="flex items-center justify-center gap-4 pt-2">
        <Link href="#" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Privacy</Link>
        <span className="text-slate-700">·</span>
        <Link href="#" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Terms</Link>
        <span className="text-slate-700">·</span>
        <Link href="#" className="text-xs text-slate-600 hover:text-slate-400 transition-colors">Help</Link>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-950">
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: "#0f172a",
            color: "#e2e8f0",
            border: "1px solid #1e293b",
            borderRadius: "10px",
            fontSize: "13px",
          },
        }}
      />

      {/* Left: Branding */}
      <div className="hidden lg:flex lg:w-1/2 relative bg-slate-900 overflow-hidden">
        {/* Background image */}
        <div
          className="absolute inset-0 z-0 opacity-30 bg-cover bg-center"
          style={{
            backgroundImage: `url('https://images.unsplash.com/photo-1589994965851-a8f479c573a9?w=1200&q=80')`,
          }}
        />
        {/* Gradient overlay */}
        <div className="absolute inset-0 z-10 bg-gradient-to-tr from-slate-950 via-slate-900/80 to-amber-900/20" />

        <div className="relative z-20 flex flex-col justify-between p-12 h-full w-full">
          {/* Logo */}
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-primary rounded-lg">
              <span className="material-symbols-outlined text-white text-2xl">gavel</span>
            </div>
            <span className="text-xl font-black tracking-tight text-white uppercase">Neethi AI</span>
          </div>

          {/* Hero */}
          <div className="max-w-xl">
            <h1 className="text-5xl font-extrabold text-white leading-tight mb-5">
              The future of Indian{" "}
              <span className="text-primary">Legal Research</span> is here.
            </h1>
            <p className="text-lg text-slate-300 leading-relaxed">
              Verified, Source-Cited Indian Legal AI designed for the modern advocate.
              Access millions of precedents in seconds.
            </p>
          </div>

          {/* Stats */}
          <div className="flex gap-6">
            <div className="flex flex-col gap-1">
              <span className="text-primary font-bold text-lg">10M+</span>
              <span className="text-slate-400 text-sm">Case Laws</span>
            </div>
            <div className="w-px h-10 bg-slate-700" />
            <div className="flex flex-col gap-1">
              <span className="text-primary font-bold text-lg">100%</span>
              <span className="text-slate-400 text-sm">Source Verified</span>
            </div>
            <div className="w-px h-10 bg-slate-700" />
            <div className="flex flex-col gap-1">
              <span className="text-primary font-bold text-lg">24/7</span>
              <span className="text-slate-400 text-sm">AI Assistance</span>
            </div>
          </div>
        </div>
      </div>

      {/* Right: Auth Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8 bg-slate-950">
        {/* Mobile logo */}
        <div className="absolute top-6 left-6 flex lg:hidden items-center gap-2">
          <div className="p-1.5 bg-primary rounded-lg">
            <span className="material-symbols-outlined text-white text-lg">gavel</span>
          </div>
          <span className="text-base font-black text-white uppercase">Neethi AI</span>
        </div>

        <Suspense fallback={<div className="text-slate-400">Loading...</div>}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
