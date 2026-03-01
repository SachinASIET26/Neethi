import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { UserRole, VerificationStatus, ConfidenceLevel } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(dateString: string): string {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function getRoleLabel(role: UserRole): string {
  const labels: Record<UserRole, string> = {
    citizen: "Citizen",
    lawyer: "Advocate",
    legal_advisor: "Legal Advisor",
    police: "Police Officer",
    admin: "Administrator",
  };
  return labels[role] || role;
}

export function getRoleColor(role: UserRole): string {
  const colors: Record<UserRole, string> = {
    citizen: "text-blue-400 bg-blue-400/10 border-blue-400/20",
    lawyer: "text-primary bg-primary/10 border-primary/20",
    legal_advisor: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    police: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    admin: "text-red-400 bg-red-400/10 border-red-400/20",
  };
  return colors[role] || "text-slate-400 bg-slate-400/10 border-slate-400/20";
}

export function getVerificationColor(status: VerificationStatus): string {
  const colors: Record<VerificationStatus, string> = {
    VERIFIED: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    PARTIALLY_VERIFIED: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    UNVERIFIED: "text-red-400 bg-red-400/10 border-red-400/20",
  };
  return colors[status];
}

export function getVerificationIcon(status: VerificationStatus): string {
  const icons: Record<VerificationStatus, string> = {
    VERIFIED: "verified",
    PARTIALLY_VERIFIED: "warning",
    UNVERIFIED: "cancel",
  };
  return icons[status];
}

export function getConfidenceColor(confidence: ConfidenceLevel): string {
  const colors: Record<ConfidenceLevel, string> = {
    high: "text-emerald-400",
    medium: "text-amber-400",
    low: "text-red-400",
  };
  return colors[confidence];
}

export function getConfidencePercent(confidence: ConfidenceLevel): number {
  const percents: Record<ConfidenceLevel, number> = {
    high: 92,
    medium: 65,
    low: 35,
  };
  return percents[confidence];
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + "...";
}

export function formatActCode(actCode: string): string {
  return actCode.replace(/_/g, " ").replace(/(\d{4})$/, ", $1");
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function playBase64Audio(base64: string): void {
  const audioBytes = atob(base64);
  const buffer = new Uint8Array(audioBytes.length);
  for (let i = 0; i < audioBytes.length; i++) {
    buffer[i] = audioBytes.charCodeAt(i);
  }
  const blob = new Blob([buffer], { type: "audio/wav" });
  const audioUrl = URL.createObjectURL(blob);
  const audio = new Audio(audioUrl);
  audio.play().catch(() => {});
}

export function getRateLimitInfo(role: UserRole): { daily: number; perMinute: number; docsDaily: number } {
  const limits = {
    citizen: { daily: 20, perMinute: 2, docsDaily: 5 },
    lawyer: { daily: 100, perMinute: 5, docsDaily: 20 },
    legal_advisor: { daily: 100, perMinute: 5, docsDaily: 20 },
    police: { daily: 50, perMinute: 5, docsDaily: 10 },
    admin: { daily: 999999, perMinute: 999999, docsDaily: 999999 },
  };
  return limits[role] || limits.citizen;
}
