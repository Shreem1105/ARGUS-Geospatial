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

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1));
}
