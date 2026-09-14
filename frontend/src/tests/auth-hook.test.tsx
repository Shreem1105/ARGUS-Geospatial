import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { useRequireAuth } from "@/hooks/auth";

const replaceMock = vi.fn();
const getMeMock = vi.fn();
let pathname = "/monitors";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => pathname,
}));

vi.mock("@/api/endpoints", () => ({
  api: {
    getMe: (...args: unknown[]) => getMeMock(...args),
  },
}));

function renderProbe() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  function Probe() {
    const auth = useRequireAuth();
    return <pre data-testid="auth-state">{JSON.stringify(auth)}</pre>;
  }

  render(
    <QueryClientProvider client={queryClient}>
      <Probe />
    </QueryClientProvider>,
  );
}

describe("useRequireAuth", () => {
  beforeEach(() => {
    pathname = "/monitors";
    replaceMock.mockReset();
    getMeMock.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("hydrates an authenticated session without redirect", async () => {
    getMeMock.mockResolvedValue({
      id: "user-1",
      email: "user@example.com",
      role: "user",
      is_active: true,
      is_verified: false,
      display_name: "User",
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
      last_login_at: null,
    });

    renderProbe();

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("auth-state").textContent ?? "{}");
      expect(parsed.isAuthenticated).toBe(true);
      expect(parsed.isRedirecting).toBe(false);
      expect(parsed.user.email).toBe("user@example.com");
    });

    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("redirects unauthenticated users to sign-in with reason", async () => {
    getMeMock.mockRejectedValue(new ApiError(401, "Invalid or expired access token"));

    renderProbe();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledTimes(1);
    });

    const redirectPath = String(replaceMock.mock.calls[0][0]);
    expect(redirectPath).toContain("/sign-in?");
    expect(redirectPath).toContain("reason=unauthenticated");
    expect(redirectPath).toContain("next=%2F");
  });

  it("does not redirect while auth state is loading", async () => {
    getMeMock.mockImplementation(() => new Promise(() => undefined));

    renderProbe();

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("auth-state").textContent ?? "{}");
      expect(parsed.isLoading).toBe(true);
      expect(parsed.isRedirecting).toBe(false);
    });

    expect(replaceMock).not.toHaveBeenCalled();
  });
});