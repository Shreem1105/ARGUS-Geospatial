import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MonitorNotificationSettings } from "@/components/monitor/notification-settings-card";

const getNotificationPreferenceMock = vi.fn();
const patchNotificationPreferenceMock = vi.fn();

vi.mock("@/api/endpoints", () => ({
  api: {
    getNotificationPreference: (...args: unknown[]) => getNotificationPreferenceMock(...args),
    patchNotificationPreference: (...args: unknown[]) => patchNotificationPreferenceMock(...args),
  },
}));

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MonitorNotificationSettings monitorId="monitor-1" />
    </QueryClientProvider>,
  );
}

describe("MonitorNotificationSettings", () => {
  beforeEach(() => {
    getNotificationPreferenceMock.mockReset();
    patchNotificationPreferenceMock.mockReset();
  });

  it("loads monitor preference and persists updates", async () => {
    getNotificationPreferenceMock.mockResolvedValue({
      id: "pref-1",
      user_id: "user-1",
      monitor_id: "monitor-1",
      in_app_enabled: true,
      email_enabled: false,
      minimum_event_severity: "low",
      minimum_semantic_confidence: null,
      notify_on_new_event: true,
      notify_on_failed_run: true,
      notify_on_partial_run: true,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    });

    patchNotificationPreferenceMock.mockResolvedValue({
      id: "pref-1",
      user_id: "user-1",
      monitor_id: "monitor-1",
      in_app_enabled: true,
      email_enabled: true,
      minimum_event_severity: "low",
      minimum_semantic_confidence: null,
      notify_on_new_event: true,
      notify_on_failed_run: true,
      notify_on_partial_run: true,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    });

    renderSettings();

    const emailToggle = await screen.findByLabelText(/Email alerts enabled/i);
    fireEvent.click(emailToggle);
    fireEvent.click(screen.getByRole("button", { name: /Save preferences/i }));

    await waitFor(() => {
      expect(patchNotificationPreferenceMock).toHaveBeenCalledTimes(1);
    });

    const payload = patchNotificationPreferenceMock.mock.calls[0][0];
    const monitorId = patchNotificationPreferenceMock.mock.calls[0][1];

    expect(payload.email_enabled).toBe(true);
    expect(monitorId).toBe("monitor-1");
    expect(screen.getByText(/Notification settings saved/i)).toBeInTheDocument();
  });
});