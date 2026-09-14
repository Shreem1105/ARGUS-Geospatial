"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/endpoints";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useRequireAuth } from "@/hooks/auth";

const PAGE_SIZE = 50;

export default function AlertsPage() {
  const auth = useRequireAuth();
  const queryClient = useQueryClient();

  const [unreadOnly, setUnreadOnly] = useState(false);
  const [offset, setOffset] = useState(0);

  const alertsQuery = useQuery({
    queryKey: ["alerts", { unreadOnly, offset }],
    queryFn: () => api.listAlerts({ unreadOnly, limit: PAGE_SIZE, offset }),
    enabled: auth.isAuthenticated,
  });

  const unreadCount = useMemo(
    () => (alertsQuery.data?.alerts ?? []).filter((alert) => alert.status === "unread").length,
    [alertsQuery.data?.alerts],
  );

  const patchMutation = useMutation({
    mutationFn: ({ alertId, status }: { alertId: string; status: "read" | "unread" }) => api.patchAlert(alertId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const readAllMutation = useMutation({
    mutationFn: api.markAllAlertsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  if (auth.isLoading || auth.isRedirecting) {
    return <LoadingState label="Checking session…" />;
  }

  if (!auth.user) {
    return <LoadingState label="Redirecting to sign in…" />;
  }

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Alert Center"
          subtitle="Run and change-event notifications for your account"
          actions={
            <div className="flex items-center gap-2 text-xs">
              <span className="rounded border border-argus-border bg-argus-panel px-2 py-1">Unread: {unreadCount}</span>
              <button
                type="button"
                className="argus-control"
                onClick={() => readAllMutation.mutate()}
                disabled={readAllMutation.isPending}
              >
                {readAllMutation.isPending ? "Updating…" : "Mark all read"}
              </button>
            </div>
          }
        />

        <div className="flex items-center justify-between border-b border-argus-border px-3 py-2 text-xs text-argus-muted">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(event) => {
                setUnreadOnly(event.target.checked);
                setOffset(0);
              }}
            />
            Unread only
          </label>

          <div className="flex items-center gap-2">
            <button type="button" className="argus-control" onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))} disabled={offset === 0}>
              Prev
            </button>
            <button
              type="button"
              className="argus-control"
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
              disabled={(alertsQuery.data?.alerts.length ?? 0) < PAGE_SIZE}
            >
              Next
            </button>
          </div>
        </div>

        {alertsQuery.isLoading ? <LoadingState label="Loading alerts…" /> : null}
        {alertsQuery.error ? <ErrorState detail={(alertsQuery.error as Error).message} /> : null}
        {patchMutation.error ? <ErrorState detail={(patchMutation.error as Error).message} /> : null}

        <div className="argus-scroll max-h-[70vh] space-y-2 overflow-y-auto p-3">
          {(alertsQuery.data?.alerts ?? []).length === 0 ? (
            <p className="text-sm text-argus-muted">No alerts found for this filter.</p>
          ) : null}

          {(alertsQuery.data?.alerts ?? []).map((alert) => {
            const eventHref = alert.change_event_id
              ? `/monitors/${alert.monitor_id}?eventId=${encodeURIComponent(alert.change_event_id)}`
              : `/monitors/${alert.monitor_id}`;

            return (
              <div key={alert.id} className="argus-panel-muted space-y-2 px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-argus-text">{alert.title}</p>
                    <p className="text-argus-muted">{alert.message}</p>
                  </div>
                  <div className="text-right text-[11px] text-argus-muted">
                    <p>{alert.severity}</p>
                    <p>{alert.status}</p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3 text-[11px] text-argus-muted">
                  <span>Type: {alert.alert_type}</span>
                  <span>Created: {alert.created_at}</span>
                  <span>Email: {alert.delivery_status}</span>
                  {alert.delivery_error ? <span>Error: {alert.delivery_error}</span> : null}
                  <Link href={eventHref} className="text-argus-accent underline underline-offset-2">
                    Open related event
                  </Link>
                </div>

                <div className="flex gap-2">
                  <button
                    type="button"
                    className="argus-control"
                    disabled={patchMutation.isPending || alert.status === "read"}
                    onClick={() => patchMutation.mutate({ alertId: alert.id, status: "read" })}
                  >
                    Mark read
                  </button>
                  <button
                    type="button"
                    className="argus-control"
                    disabled={patchMutation.isPending || alert.status === "unread"}
                    onClick={() => patchMutation.mutate({ alertId: alert.id, status: "unread" })}
                  >
                    Mark unread
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}