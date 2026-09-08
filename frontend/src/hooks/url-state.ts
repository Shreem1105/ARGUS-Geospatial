"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

function parseSearch(search: string): Record<string, string> {
  const result: Record<string, string> = {};
  const params = new URLSearchParams(search);
  params.forEach((value, key) => {
    result[key] = value;
  });
  return result;
}

export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const [values, setCurrentValues] = useState<Record<string, string>>(() => {
    if (typeof window === "undefined") {
      return {};
    }
    return parseSearch(window.location.search);
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const sync = () => {
      setCurrentValues(parseSearch(window.location.search));
    };

    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const setValues = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      if (typeof window === "undefined") {
        return;
      }

      const next = new URLSearchParams(window.location.search);
      Object.entries(updates).forEach(([key, value]) => {
        if (!value) {
          next.delete(key);
          return;
        }
        next.set(key, value);
      });

      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
      setCurrentValues(parseSearch(query ? `?${query}` : ""));
    },
    [pathname, router],
  );

  return { values, setValues };
}
