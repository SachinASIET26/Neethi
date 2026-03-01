import { create } from "zustand";
import { persist } from "zustand/middleware";
import Cookies from "js-cookie";
import type { UserProfile, UserRole } from "@/types";

interface AuthState {
  user: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;

  setAuth: (token: string, user: UserProfile) => void;
  setUser: (user: UserProfile) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      setAuth: (token, user) => {
        Cookies.set("neethi_token", token, {
          expires: 1,
          secure: process.env.NODE_ENV === "production",
          sameSite: "strict",
        });
        set({ token, user, isAuthenticated: true });
      },

      setUser: (user) => {
        set({ user });
      },

      clearAuth: () => {
        Cookies.remove("neethi_token");
        set({ token: null, user: null, isAuthenticated: false });
      },
    }),
    {
      name: "neethi-auth",
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);

// Selectors
export const selectUser = (state: AuthState) => state.user;
export const selectRole = (state: AuthState): UserRole | null => state.user?.role ?? null;
export const selectIsAuthenticated = (state: AuthState) => state.isAuthenticated;
