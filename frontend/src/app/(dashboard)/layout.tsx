"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { useAuthStore } from "@/store/auth";
import { authAPI } from "@/lib/api";
import { Toaster } from "react-hot-toast";
import { useTheme } from "next-themes";

function ToasterWrapper() {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        style: isDark
          ? {
              background: "#0f172a",
              color: "#e2e8f0",
              border: "1px solid #1e293b",
              borderRadius: "10px",
              fontSize: "13px",
            }
          : {
              background: "#ffffff",
              color: "#0f172a",
              border: "1px solid #e2e8f0",
              borderRadius: "10px",
              fontSize: "13px",
              boxShadow: "0 4px 20px rgba(0,0,0,0.1)",
            },
        success: {
          iconTheme: { primary: "#db7706", secondary: isDark ? "#0f172a" : "#ffffff" },
        },
      }}
    />
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { isAuthenticated, setUser, clearAuth } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      router.replace("/login");
      return;
    }

    authAPI.me().then(setUser).catch(() => {
      clearAuth();
      router.replace("/login");
    });
  }, [isAuthenticated, router, setUser, clearAuth]);

  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-gray-50 dark:bg-[#020617]">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto custom-scrollbar bg-gray-50 dark:bg-[#020617]">
          {children}
        </main>
      </div>
      <ToasterWrapper />
    </div>
  );
}
