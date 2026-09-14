import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import SignInPage from "../../app/sign-in/page";
import RegisterPage from "../../app/register/page";

const replaceMock = vi.fn();
const loginMock = vi.fn();
const registerMock = vi.fn();
const setAuthSessionUserMock = vi.fn();

let sessionState: { isLoading: boolean; data: unknown | null } = {
  isLoading: false,
  data: null,
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
}));

vi.mock("@/api/endpoints", () => ({
  api: {
    login: (...args: unknown[]) => loginMock(...args),
    register: (...args: unknown[]) => registerMock(...args),
  },
}));

vi.mock("@/hooks/auth", () => ({
  AUTH_SESSION_QUERY_KEY: ["auth", "session"],
  setAuthSessionUser: (...args: unknown[]) => setAuthSessionUserMock(...args),
  useAuthSession: () => sessionState,
}));

function renderWithQueryClient(element: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
  return queryClient;
}

function resetLocation(path: string) {
  window.history.replaceState({}, "", path);
}

describe("auth pages", () => {
  beforeEach(() => {
    sessionState = { isLoading: false, data: null };
    replaceMock.mockReset();
    loginMock.mockReset();
    registerMock.mockReset();
    setAuthSessionUserMock.mockReset();
    resetLocation("/");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("submits sign-in credentials and redirects to requested path", async () => {
    resetLocation("/sign-in?next=%2Fruns&reason=expired");

    loginMock.mockResolvedValue({
      user: { id: "user-1", email: "user@example.com" },
      access_token_expires_at: "2026-09-15T00:00:00Z",
      refresh_token_expires_at: "2026-09-30T00:00:00Z",
      csrf_token: "csrf-token",
    });

    renderWithQueryClient(<SignInPage />);

    expect(screen.getByText(/session expired/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^Email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password/i), { target: { value: "StrongerPass!234" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith({ email: "user@example.com", password: "StrongerPass!234" });
      expect(setAuthSessionUserMock).toHaveBeenCalledTimes(1);
      expect(replaceMock).toHaveBeenCalledWith("/runs");
    });
  });

  it("shows loading state while auth session is hydrating", () => {
    sessionState = { isLoading: true, data: null };

    renderWithQueryClient(<SignInPage />);

    expect(screen.getByText(/Checking session/i)).toBeInTheDocument();
  });

  it("submits registration payload and redirects to requested path", async () => {
    resetLocation("/register?next=%2Fmonitors%2Fabc");

    registerMock.mockResolvedValue({
      user: { id: "user-2", email: "new@example.com" },
      access_token_expires_at: "2026-09-15T00:00:00Z",
      refresh_token_expires_at: "2026-09-30T00:00:00Z",
      csrf_token: "csrf-token",
    });

    renderWithQueryClient(<RegisterPage />);

    fireEvent.change(screen.getByLabelText(/^Email/i), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Display name/i), { target: { value: "New User" } });
    fireEvent.change(screen.getByLabelText(/^Password/i), { target: { value: "VeryStrongPass!567" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledWith({
        email: "new@example.com",
        password: "VeryStrongPass!567",
        display_name: "New User",
      });
      expect(setAuthSessionUserMock).toHaveBeenCalledTimes(1);
      expect(replaceMock).toHaveBeenCalledWith("/monitors/abc");
    });
  });
});