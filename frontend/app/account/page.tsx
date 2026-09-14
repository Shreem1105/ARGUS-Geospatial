"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { ErrorState, LoadingState, Metric, Panel, PanelHeader } from "@/components/ui";
import { AUTH_SESSION_QUERY_KEY, clearAuthSession, useRequireAuth } from "@/hooks/auth";
import type { AuthUser, NotificationPreference } from "@/types/api";

type PreferenceDraft = {
  in_app_enabled: boolean;
  email_enabled: boolean;
  minimum_event_severity: "low" | "medium" | "high" | "critical";
  minimum_semantic_confidence: number | null;
  notify_on_new_event: boolean;
  notify_on_failed_run: boolean;
  notify_on_partial_run: boolean;
};

function toPreferenceDraft(preference: NotificationPreference): PreferenceDraft {
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

function formatLimit(value: number | null): string {
  return value === null ? "unlimited" : String(value);
}

export default function AccountPage() {
  const auth = useRequireAuth();

  if (auth.isLoading || auth.isRedirecting) {
    return <LoadingState label="Checking session…" />;
  }

  if (!auth.user) {
    return <LoadingState label="Redirecting to sign in…" />;
  }

  return <AccountWorkspace user={auth.user} />;
}

function AccountWorkspace({ user }: { user: AuthUser }) {
  const queryClient = useQueryClient();
  const router = useRouter();

  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [prefDraft, setPrefDraft] = useState<PreferenceDraft | null>(null);

  const quotaQuery = useQuery({ queryKey: ["account-quota"], queryFn: api.getAccountQuota });
  const usageQuery = useQuery({ queryKey: ["account-usage"], queryFn: api.getAccountUsage });
  const preferenceQuery = useQuery({
    queryKey: ["account-notification-preference", "global"],
    queryFn: () => api.getNotificationPreference(),
    retry: false,
  });

  const baselineDraft = useMemo(() => {
    if (!preferenceQuery.data) {
      return null;
    }
    return toPreferenceDraft(preferenceQuery.data);
  }, [preferenceQuery.data]);

  const effectivePrefDraft = prefDraft ?? baselineDraft;

  const hasChanges = useMemo(() => {
    if (!baselineDraft || !effectivePrefDraft) {
      return false;
    }
    return JSON.stringify(baselineDraft) !== JSON.stringify(effectivePrefDraft);
  }, [baselineDraft, effectivePrefDraft]);

  const updatePreferenceDraft = (updater: (current: PreferenceDraft) => PreferenceDraft) => {
    setPrefDraft((previous) => {
      const base = previous ?? baselineDraft;
      if (!base) {
        return previous;
      }
      return updater(base);
    });
    setSaveMessage(null);
  };

  const savePreferenceMutation = useMutation({
    mutationFn: (payload: PreferenceDraft) => api.patchNotificationPreference(payload),
    onSuccess: (saved) => {
      queryClient.setQueryData(["account-notification-preference", "global"], saved);
      setPrefDraft(toPreferenceDraft(saved));
      setSaveMessage("Notification settings saved.");
    },
  });

  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      clearAuthSession(queryClient);
      await queryClient.invalidateQueries({ queryKey: AUTH_SESSION_QUERY_KEY });
      router.replace("/sign-in");
    },
  });

  const logoutAllMutation = useMutation({
    mutationFn: api.logoutAll,
    onSuccess: async () => {
      clearAuthSession(queryClient);
      await queryClient.invalidateQueries({ queryKey: AUTH_SESSION_QUERY_KEY });
      router.replace("/sign-in");
    },
  });

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Account"
          subtitle="Authenticated ARGUS user profile and quota"
          actions={
            <div className="flex gap-2">
              <button type="button" className="argus-control" onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending}>
                {logoutMutation.isPending ? "Signing out…" : "Sign out"}
              </button>
              <button
                type="button"
                className="argus-control"
                onClick={() => logoutAllMutation.mutate()}
                disabled={logoutAllMutation.isPending}
              >
                {logoutAllMutation.isPending ? "Revoking…" : "Sign out all"}
              </button>
            </div>
          }
        />

        <div className="grid gap-2 p-3 text-sm md:grid-cols-2">
          <Metric label="Email" value={user.email} />
          <Metric label="Role" value={user.role} />
          <Metric label="Display Name" value={user.display_name ?? "—"} />
          <Metric label="Last Login" value={user.last_login_at ?? "—"} />
        </div>
      </Panel>

      {actionError ? <ErrorState detail={actionError} /> : null}
      {quotaQuery.error ? <ErrorState detail={(quotaQuery.error as Error).message} /> : null}
      {usageQuery.error ? <ErrorState detail={(usageQuery.error as Error).message} /> : null}

      <Panel>
        <PanelHeader title="Quota" subtitle="Usage, limits, and remaining capacity" />
        {quotaQuery.isLoading ? (
          <LoadingState label="Loading quota…" />
        ) : quotaQuery.data ? (
          <div className="grid gap-2 p-3 text-sm md:grid-cols-3">
            <Metric label="Monitors" value={`${quotaQuery.data.usage.monitor_count}/${formatLimit(quotaQuery.data.limits.max_monitors)}`} />
            <Metric
              label="Active Monitors"
              value={`${quotaQuery.data.usage.active_monitor_count}/${formatLimit(quotaQuery.data.limits.max_active_monitors)}`}
            />
            <Metric
              label="Manual Runs Today"
              value={`${quotaQuery.data.usage.manual_runs_today}/${formatLimit(quotaQuery.data.limits.max_manual_runs_per_day)}`}
            />
            <Metric
              label="Observation Searches Today"
              value={`${quotaQuery.data.usage.observation_searches_today}/${formatLimit(quotaQuery.data.limits.max_observation_searches_per_day)}`}
            />
            <Metric
              label="Semantic Runs Today"
              value={`${quotaQuery.data.usage.semantic_runs_today}/${formatLimit(quotaQuery.data.limits.max_semantic_runs_per_day)}`}
            />
            <Metric
              label="Concurrent Jobs"
              value={`${quotaQuery.data.usage.concurrent_jobs}/${formatLimit(quotaQuery.data.limits.max_concurrent_jobs)}`}
            />
            <Metric
              label="AOI Area Limit (km²)"
              value={quotaQuery.data.limits.max_aoi_area_km2 === null ? "unlimited" : quotaQuery.data.limits.max_aoi_area_km2.toFixed(2)}
            />
            <Metric label="Resets (UTC)" value={quotaQuery.data.resets_at_utc} />
          </div>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader title="Usage" subtitle="Daily usage counters" />
        {usageQuery.isLoading ? (
          <LoadingState label="Loading usage…" />
        ) : usageQuery.data ? (
          <div className="grid gap-2 p-3 text-sm md:grid-cols-2">
            {Object.entries(usageQuery.data.usage_today).map(([key, value]) => (
              <Metric key={key} label={key} value={String(value)} />
            ))}
          </div>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader title="Notification Preferences" subtitle="Account-level alert and email settings" />
        {preferenceQuery.isLoading ? (
          <LoadingState label="Loading notification preferences…" />
        ) : preferenceQuery.error ? (
          <ErrorState detail={(preferenceQuery.error as Error).message} />
        ) : effectivePrefDraft ? (
          <div className="grid gap-2 p-3 text-sm">
            <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
              <span>In-app notifications</span>
              <input
                type="checkbox"
                checked={effectivePrefDraft.in_app_enabled}
                onChange={(event) => updatePreferenceDraft((current) => ({ ...current, in_app_enabled: event.target.checked }))}
              />
            </label>

            <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
              <span>Email notifications</span>
              <input
                type="checkbox"
                checked={effectivePrefDraft.email_enabled}
                onChange={(event) => updatePreferenceDraft((current) => ({ ...current, email_enabled: event.target.checked }))}
              />
            </label>

            <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
              <span>Notify on new event</span>
              <input
                type="checkbox"
                checked={effectivePrefDraft.notify_on_new_event}
                onChange={(event) => updatePreferenceDraft((current) => ({ ...current, notify_on_new_event: event.target.checked }))}
              />
            </label>

            <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
              <span>Notify on failed run</span>
              <input
                type="checkbox"
                checked={effectivePrefDraft.notify_on_failed_run}
                onChange={(event) => updatePreferenceDraft((current) => ({ ...current, notify_on_failed_run: event.target.checked }))}
              />
            </label>

            <label className="argus-panel-muted flex items-center justify-between px-3 py-2">
              <span>Notify on partial run</span>
              <input
                type="checkbox"
                checked={effectivePrefDraft.notify_on_partial_run}
                onChange={(event) => updatePreferenceDraft((current) => ({ ...current, notify_on_partial_run: event.target.checked }))}
              />
            </label>

            <label className="argus-panel-muted flex items-center justify-between gap-2 px-3 py-2">
              <span>Minimum severity</span>
              <select
                value={effectivePrefDraft.minimum_event_severity}
                onChange={(event) =>
                  updatePreferenceDraft((current) => ({
                    ...current,
                    minimum_event_severity: event.target.value as PreferenceDraft["minimum_event_severity"],
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
                value={effectivePrefDraft.minimum_semantic_confidence ?? ""}
                onChange={(event) => {
                  const raw = event.target.value.trim();
                  updatePreferenceDraft((current) => {
                    if (!raw) {
                      return { ...current, minimum_semantic_confidence: null };
                    }
                    const numeric = Number(raw);
                    if (Number.isNaN(numeric)) {
                      return current;
                    }
                    return { ...current, minimum_semantic_confidence: Math.max(0, Math.min(1, numeric)) };
                  });
                }}
                className="argus-field w-32"
              />
            </label>

            {saveMessage ? <p className="text-argus-good">{saveMessage}</p> : null}
            {savePreferenceMutation.error ? <ErrorState detail={(savePreferenceMutation.error as Error).message} /> : null}

            <div className="flex justify-end">
              <button
                type="button"
                className="argus-control"
                disabled={savePreferenceMutation.isPending || !hasChanges}
                onClick={async () => {
                  if (!effectivePrefDraft) {
                    return;
                  }
                  setSaveMessage(null);
                  setActionError(null);
                  try {
                    await savePreferenceMutation.mutateAsync(effectivePrefDraft);
                  } catch (err) {
                    if (err instanceof ApiError) {
                      setActionError(err.detail);
                    } else {
                      setActionError("Unable to save notification settings.");
                    }
                  }
                }}
              >
                {savePreferenceMutation.isPending ? "Saving…" : "Save notification settings"}
              </button>
            </div>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}