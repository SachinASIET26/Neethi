"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useUIStore } from "@/store/ui";
import { getRoleLabel, getRoleColor, cn } from "@/lib/utils";
import type { UserRole } from "@/types";

interface NavItem {
  href: string;
  icon: string;
  label: string;
  roles?: UserRole[];
}

const navItems: NavItem[] = [
  { href: "/dashboard", icon: "dashboard", label: "Dashboard" },
  { href: "/query", icon: "forum", label: "Legal Assistant" },
  { href: "/cases", icon: "work", label: "Cases" },
  { href: "/documents/draft", icon: "edit_note", label: "Drafting" },
  { href: "/statutes", icon: "balance", label: "Statutes" },
  { href: "/resources", icon: "location_on", label: "Resources" },
  { href: "/history", icon: "history", label: "History" },
];

const lawyerItems: NavItem[] = [
  {
    href: "/cases/analyze",
    icon: "analytics",
    label: "Case Analysis",
    roles: ["lawyer", "legal_advisor"],
  },
];

const ROLE_ICONS: Record<UserRole, string> = {
  citizen: "person",
  lawyer: "gavel",
  legal_advisor: "business_center",
  police: "local_police",
  admin: "admin_panel_settings",
};

export default function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuthStore();
  const { sidebarCollapsed, toggleSidebar, mobileSidebarOpen, setMobileSidebarOpen } = useUIStore();

  const allNavItems = [
    ...navItems,
    ...(user && ["lawyer", "legal_advisor"].includes(user.role) ? lawyerItems : []),
  ];

  const closeMobile = () => setMobileSidebarOpen(false);

  const sidebarContent = (isMobile: boolean) => (
    <aside
      className={cn(
        "flex flex-col border-r transition-all duration-300 ease-in-out",
        "border-gray-200 dark:border-slate-800",
        "bg-white dark:bg-[#020617]",
        "h-full",
        isMobile ? "w-72" : sidebarCollapsed ? "w-[68px]" : "w-64"
      )}
    >
      {/* Logo + Toggle */}
      <div
        className={cn(
          "flex items-center border-b border-gray-200 dark:border-slate-800 flex-shrink-0",
          !isMobile && sidebarCollapsed ? "p-3 justify-center" : "p-4 gap-3"
        )}
      >
        <div className="bg-primary rounded-lg p-2 flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-white text-xl font-bold">gavel</span>
        </div>
        {(isMobile || !sidebarCollapsed) && (
          <div className="flex-1 min-w-0">
            <h1 className="text-gray-900 dark:text-white text-base font-bold leading-tight">Neethi AI</h1>
            <p className="text-primary text-[10px] font-semibold uppercase tracking-widest">Legal Suite</p>
          </div>
        )}
        {isMobile && (
          <button
            onClick={closeMobile}
            className="ml-auto p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        )}
      </div>

      {/* Collapse Toggle Button (desktop only) */}
      {!isMobile && (
        <button
          onClick={toggleSidebar}
          className={cn(
            "flex items-center gap-2 mx-3 my-2 px-2 py-1.5 rounded-lg text-xs font-medium transition-all",
            "text-gray-500 dark:text-slate-500 hover:bg-gray-100 dark:hover:bg-slate-800/50",
            "hover:text-gray-700 dark:hover:text-slate-300",
            sidebarCollapsed ? "justify-center" : "justify-between"
          )}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {!sidebarCollapsed && (
            <span className="text-[11px] uppercase tracking-wider font-semibold">Menu</span>
          )}
          <span className="material-symbols-outlined text-[18px]">
            {sidebarCollapsed ? "chevron_right" : "chevron_left"}
          </span>
        </button>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-2 py-1 space-y-0.5 overflow-y-auto custom-scrollbar">
        {allNavItems.map((item) => {
          const isActive =
            pathname === item.href || pathname.startsWith(item.href + "/");
          const collapsed = !isMobile && sidebarCollapsed;

          return (
            <Link
              key={item.href}
              href={item.href}
              title={collapsed ? item.label : undefined}
              onClick={isMobile ? closeMobile : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg text-sm font-medium transition-all duration-150 group",
                collapsed ? "px-2 py-2.5 justify-center" : "px-3 py-2.5",
                isActive
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800/50 hover:text-gray-900 dark:hover:text-white border border-transparent"
              )}
            >
              <span
                className={cn(
                  "material-symbols-outlined text-[20px] flex-shrink-0 transition-transform duration-150",
                  isActive ? "" : "group-hover:scale-110"
                )}
              >
                {item.icon}
              </span>
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* User Role Badge */}
      {user && (
        <div
          className={cn(
            "border-t border-gray-200 dark:border-slate-800",
            !isMobile && sidebarCollapsed ? "p-3" : "p-4"
          )}
        >
          {!isMobile && sidebarCollapsed ? (
            <div
              className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto"
              title={`${user.full_name} — ${getRoleLabel(user.role)}`}
            >
              <span className="material-symbols-outlined text-primary text-[18px]">
                {ROLE_ICONS[user.role] || "person"}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0">
                <span className="material-symbols-outlined text-primary text-[18px]">
                  {ROLE_ICONS[user.role] || "person"}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                  {user.full_name?.split(" ")[0]}
                </p>
                <span
                  className={cn(
                    "inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wide",
                    getRoleColor(user.role)
                  )}
                >
                  {getRoleLabel(user.role)}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <div className="hidden md:flex flex-shrink-0">
        {sidebarContent(false)}
      </div>

      {/* Mobile drawer overlay */}
      {mobileSidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={closeMobile}
          />
          {/* Drawer */}
          <div className="relative z-10 flex-shrink-0 animate-slide-in-left">
            {sidebarContent(true)}
          </div>
        </div>
      )}
    </>
  );
}
