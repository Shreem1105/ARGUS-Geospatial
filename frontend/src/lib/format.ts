import { formatDistanceToNow, formatISO9075 } from "date-fns";

export function formatNumber(value: number | null | undefined, fractionDigits = 2): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: fractionDigits }).format(value);
}

export function formatMeters(value: number | null | undefined): string {
  if (value == null) {
    return "—";
  }
  if (Math.abs(value) >= 1000) {
    return `${formatNumber(value / 1000, 2)} km`;
  }
  return `${formatNumber(value, 1)} m`;
}

export function formatArea(value: number | null | undefined): string {
  if (value == null) {
    return "—";
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${formatNumber(value / 1_000_000, 2)} km²`;
  }
  return `${formatNumber(value, 1)} m²`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value == null) {
    return "—";
  }
  return `${formatNumber(value, digits)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return formatISO9075(date);
}

export function formatDateUtc(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const mm = String(date.getUTCMinutes()).padStart(2, "0");
  const ss = String(date.getUTCSeconds()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}:${ss} UTC`;
}

export function fromNow(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return formatDistanceToNow(date, { addSuffix: true });
}

export function formatElapsed(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) {
    return "—";
  }

  const startMs = new Date(start).getTime();
  if (Number.isNaN(startMs)) {
    return "—";
  }

  const endMs = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(endMs)) {
    return "—";
  }

  const totalSeconds = Math.max(0, Math.round((endMs - startMs) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  }
  return `${seconds}s`;
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1));
}
