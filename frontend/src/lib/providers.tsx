"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { PropsWithChildren, useEffect, useState } from "react";

import { AUTH_SESSION_QUERY_KEY } from "@/hooks/auth";

function AuthSessionSync() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const onAuthExpired = () => {
      queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, null);
      queryClient.invalidateQueries({ queryKey: AUTH_SESSION_QUERY_KEY }).catch(() => undefined);
    };

    window.addEventListener("argus:auth-expired", onAuthExpired as EventListener);
    return () => {
      window.removeEventListener("argus:auth-expired", onAuthExpired as EventListener);
    };
  }, [queryClient]);

  return null;
}

export function Providers({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthSessionSync />
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}