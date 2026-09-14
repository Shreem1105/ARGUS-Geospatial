"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/endpoints";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import type { NotificationPreference } from "@/types/api";

type MonitorNotificationSettingsProps = {
  monitorId: string;
};

type DraftPreference = {
  in_app_enabled: boolean;
  email_enabled: boolean;
  minimum_event_severity: "low" | "medium" | "high" | "critical";
  minimum_semantic_confidence: number | null;
  notify_on_new_event: boolean;
  notify_on_failed_run: boolean;
  notify_on_partial_run: boolean;
};

function toDraft(preference: NotificationPreference): DraftPreference {
  return {
    in_app_enabled: preference.in_app_enabled,
    email_enabled: preference.email_enabled,
    minimum_event_severity: preference.minimum_event_severity,
    minimum_semantic_confidence: preference.minimum_semantic_confidence,
    notify_on_new_event: preference.notify_on_new_event,
    notify_on_failed_run: preference.notify_on_failed_run,
    notify_on_partial_run: preference.notify_on_partial_run,
  };
}

export function MonitorNotificationSettings({ monitorId }: MonitorNotificationSettingsProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<DraftPreference | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const preferenceQuery = useQuery({
    queryKey: ["monitor-notification-preference", monitorId],
    queryFn: () => api.getNotificationPreference(monitorId),
    retry: false,
  });

  const baselineDraft = useMemo(() => {
    if (!preferenceQuery.data) {
      return null;
    }
    return toDraft(preferenceQuery.data);
  }, [preferenceQuery.data]);

  const effectiveDraft = draft ?? baselineDraft;

  const hasChanges = useMemo(() => {
    if (!baselineDraft || !effectiveDraft) {
      return false;
    }
    return JSON.stringify(baselineDraft) !== JSON.stringify(effectiveDraft);
  }, [baselineDraft, effectiveDraft]);

  const updateDraft = (updater: (current: DraftPreference) => DraftPreference) => {
    setDraft((previous) => {
      const base = previous ?? baselineDraft;
      if (!base) {
        return previous;
      }
      return updater(base);
    });
    setSaveMessage(null);
  };

  const saveMutation = useMutation({
    mutationFn: (payload: DraftPreference) => api.patchNotificationPreference(payload, monitorId),
    onSuccess: (saved) => {
      queryClient.setQueryData(["monitor-notification-preference", monitorId], saved);
      setDraft(toDraft(saved));
      setSaveMessage("Notification settings saved.");
    },
  });

  if (preferenceQuery.isLoading) {
    return <LoadingState label="Loading notification settings…" />;
  }

  if (preferenceQuery.error) {
    return <ErrorState detail={(preferenceQuery.error as Error).message} />;
  }

  if (!effectiveDraft) {
    return null;
  }

  return (
    <Panel className="p-3">
      <PanelHeader title="Notification Settings" subtitle="Monitor-specific in-app and email alerts" />
      <div className="mt-3 grid gap-2 text-xs">
        <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
          <span>In-app alerts enabled</span>
          <input type="checkbox" checked={effectiveDraft.in_app_enabled} onChange={(event) => updateDraft((current) => ({ ...current, in_app_enabled: event.target.checked }))} />
        </label>

        <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
          <span>Email alerts enabled</span>
          <input type="checkbox" checked={effectiveDraft.email_enabled} onChange={(event) => updateDraft((current) => ({ ...current, email_enabled: event.target.checked }))} />
        </label>

        <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
          <span>Notify on new events</span>
          <input type="checkbox" checked={effectiveDraft.notify_on_new_event} onChange={(event) => updateDraft((current) => ({ ...current, notify_on_new_event: event.target.checked }))} />
        </label>

        <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
          <span>Notify on failed runs</span>
          <input type="checkbox" checked={effectiveDraft.notify_on_failed_run} onChange={(event) => updateDraft((current) => ({ ...current, notify_on_failed_run: event.target.checked }))} />
        </label>

        <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
          <span>Notify on partial runs</span>
          <input type="checkbox" checked={effectiveDraft.notify_on_partial_run} onChange={(event) => updateDraft((current) => ({ ...current, notify_on_partial_run: event.target.checked }))} />
        </label>

        <label className="argus-panel-muted flex items-center justify-between gap-2 px-3 py-2">
          <span>Minimum event severity</span>
          <select
            value={effectiveDraft.minimum_event_severity}
            onChange={(event) =>
              updateDraft((current) => ({
                ...current,
                minimum_event_severity: event.target.value as DraftPreference["minimum_event_severity"],
              }))
            }
            className="argus-field"
          >
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
        </label>

        <label className="argus-panel-muted flex items-center justify-between gap-2 px-3 py-2">
          <span>Minimum semantic confidence</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={effectiveDraft.minimum_semantic_confidence ?? ""}
            onChange={(event) => {
              const next = event.target.value.trim();
              updateDraft((current) => {
                if (!next) {
                  return { ...current, minimum_semantic_confidence: null };
                }
                const numeric = Number(next);
                if (Number.isNaN(numeric)) {
                  return current;
                }
                const clamped = Math.max(0, Math.min(1, numeric));
                return { ...current, minimum_semantic_confidence: clamped };
              });
            }}
            className="argus-field w-28"
            placeholder="none"
          />
        </label>
      </div>

      {saveMessage ? <p className="mt-3 text-xs text-argus-good">{saveMessage}</p> : null}
      {saveMutation.error ? (
        <div className="mt-3">
          <ErrorState detail={(saveMutation.error as Error).message} />
        </div>
      ) : null}

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          className="argus-control"
          disabled={!hasChanges || saveMutation.isPending}
          onClick={() => {
            setSaveMessage(null);
            if (!effectiveDraft) {
              return;
            }
            saveMutation.mutate(effectiveDraft);
          }}
        >
          {saveMutation.isPending ? "Saving…" : "Save preferences"}
        </button>
      </div>
    </Panel>
  );
}