import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AlertsPage from "../../app/alerts/page";

const listAlertsMock = vi.fn();
const patchAlertMock = vi.fn();
const markAllAlertsReadMock = vi.fn();

let authState: {
  isLoading: boolean;
  isRedirecting: boolean;
  isAuthenticated: boolean;
  user: { id: string; email: string } | null;
} = {
  isLoading: false,
  isRedirecting: false,
  isAuthenticated: true,
  user: { id: "user-1", email: "owner@example.com" },
};

vi.mock("@/api/endpoints", () => ({
  api: {
    listAlerts: (...args: unknown[]) => listAlertsMock(...args),
    patchAlert: (...args: unknown[]) => patchAlertMock(...args),
    markAllAlertsRead: (...args: unknown[]) => markAllAlertsReadMock(...args),
  },
}));

vi.mock("@/hooks/auth", () => ({
  useRequireAuth: () => authState,
}));

function renderAlertsPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <AlertsPage />
    </QueryClientProvider>,
  );
}

function sampleAlert(overrides?: Partial<Record<string, unknown>>) {
  return {
    id: "alert-1",
    user_id: "user-1",
    monitor_id: "monitor-1",
    monitor_run_id: null,
    change_event_id: "event-1",
    alert_type: "new_event",
    severity: "high",
    title: "Change detected",
    message: "A new change event was detected",
    status: "unread",
    created_at: "2026-09-14T12:00:00Z",
    read_at: null,
    delivery_status: "disabled",
    delivery_error: null,
    metadata: {},
    ...overrides,
  };
}

describe("AlertsPage", () => {
  beforeEach(() => {
    authState = {
      isLoading: false,
      isRedirecting: false,
      isAuthenticated: true,
      user: { id: "user-1", email: "owner@example.com" },
    };
    listAlertsMock.mockReset();
    patchAlertMock.mockReset();
    markAllAlertsReadMock.mockReset();
  });

  it("renders unread badge and alert details", async () => {
    listAlertsMock.mockResolvedValue({
      count: 2,
      alerts: [sampleAlert(), sampleAlert({ id: "alert-2", status: "read" })],
    });

    renderAlertsPage();

    expect(await screen.findByText(/Alert Center/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Unread:\s*1/i)).toBeInTheDocument();
    });
    expect(screen.getAllByText(/Type: new_event/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Email: disabled/i).length).toBeGreaterThan(0);
  });

  it("persists mark read action", async () => {
    listAlertsMock.mockResolvedValue({
      count: 1,
      alerts: [sampleAlert({ status: "unread" })],
    });
    patchAlertMock.mockResolvedValue(sampleAlert({ status: "read" }));

    renderAlertsPage();

    const markReadButton = await screen.findByRole("button", { name: /Mark read/i });
    fireEvent.click(markReadButton);

    await waitFor(() => {
      expect(patchAlertMock).toHaveBeenCalledWith("alert-1", "read");
    });
  });

  it("persists mark unread action", async () => {
    listAlertsMock.mockResolvedValue({
      count: 1,
      alerts: [sampleAlert({ status: "read" })],
    });
    patchAlertMock.mockResolvedValue(sampleAlert({ status: "unread" }));

    renderAlertsPage();

    const markUnreadButton = await screen.findByRole("button", { name: /Mark unread/i });
    fireEvent.click(markUnreadButton);

    await waitFor(() => {
      expect(patchAlertMock).toHaveBeenCalledWith("alert-1", "unread");
    });
  });
});