"use client";

import { QueryClient, useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { buildCurrentPath, buildSignInHref, sanitizeNextPath } from "@/lib/auth";
import type { AuthSession, AuthUser } from "@/types/api";

export const AUTH_SESSION_QUERY_KEY = ["auth", "session"] as const;

async function fetchAuthUser(): Promise<AuthUser | null> {
  try {
    return await api.getMe();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export function useAuthSession() {
  return useQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: fetchAuthUser,
    staleTime: 30_000,
    retry: false,
  });
}

export function setAuthSessionUser(queryClient: QueryClient, session: AuthSession | AuthUser | null) {
  if (!session) {
    queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, null);
    return;
  }

  if ("user" in session) {
    queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, session.user);
    return;
  }

  queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, session);
}

export function clearAuthSession(queryClient: QueryClient) {
  queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, null);
}

export function useRequireAuth() {
  const session = useAuthSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (session.isLoading || session.data) {
      return;
    }

    const nextPath = typeof window === "undefined"
      ? buildCurrentPath(pathname ?? "/", null)
      : buildCurrentPath(window.location.pathname, window.location.search);

    const href = buildSignInHref(sanitizeNextPath(nextPath), "unauthenticated");
    router.replace(href);
  }, [pathname, router, session.data, session.isLoading]);

  return {
    user: session.data ?? null,
    isAuthenticated: Boolean(session.data),
    isLoading: session.isLoading,
    isRedirecting: !session.isLoading && !session.data,
  };
}