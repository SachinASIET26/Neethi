import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface BadgeProps {
  children: ReactNode;
  variant?: "default" | "primary" | "success" | "warning" | "danger" | "info" | "outline";
  size?: "sm" | "md";
  icon?: string;
  className?: string;
}

export default function Badge({
  children,
  variant = "default",
  size = "sm",
  icon,
  className,
}: BadgeProps) {
  const variants = {
    default: "bg-slate-800 text-slate-300 border-slate-700",
    primary: "bg-primary/10 text-primary border-primary/20",
    success: "bg-emerald-400/10 text-emerald-400 border-emerald-400/20",
    warning: "bg-amber-400/10 text-amber-400 border-amber-400/20",
    danger: "bg-red-400/10 text-red-400 border-red-400/20",
    info: "bg-blue-400/10 text-blue-400 border-blue-400/20",
    outline: "bg-transparent text-slate-400 border-slate-700",
  };

  const sizes = {
    sm: "text-xs px-2 py-0.5",
    md: "text-sm px-2.5 py-1",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border font-medium",
        variants[variant],
        sizes[size],
        className
      )}
    >
      {icon && (
        <span className="material-symbols-outlined text-[12px]">{icon}</span>
      )}
      {children}
    </span>
  );
}
