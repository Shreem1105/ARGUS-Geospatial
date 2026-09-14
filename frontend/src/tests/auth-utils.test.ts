import { describe, expect, it } from "vitest";

import {
  DEFAULT_AUTH_REDIRECT_PATH,
  buildCurrentPath,
  buildSignInHref,
  isProtectedRoute,
  sanitizeNextPath,
} from "@/lib/auth";

describe("auth route helpers", () => {
  it("marks protected and public routes correctly", () => {
    expect(isProtectedRoute("/monitors")).toBe(true);
    expect(isProtectedRoute("/monitors/123")).toBe(true);
    expect(isProtectedRoute("/runs")).toBe(true);

    expect(isProtectedRoute("/")).toBe(false);
    expect(isProtectedRoute("/explore")).toBe(false);
    expect(isProtectedRoute("/explore/case-a")).toBe(false);
    expect(isProtectedRoute("/sign-in")).toBe(false);
    expect(isProtectedRoute("/register")).toBe(false);
  });

  it("builds current path with and without query string", () => {
    expect(buildCurrentPath("/monitors", "?a=1")).toBe("/monitors?a=1");
    expect(buildCurrentPath("/monitors", "a=1")).toBe("/monitors?a=1");
    expect(buildCurrentPath("/monitors", null)).toBe("/monitors");
  });

  it("sanitizes invalid next paths to default redirect", () => {
    expect(sanitizeNextPath(undefined)).toBe(DEFAULT_AUTH_REDIRECT_PATH);
    expect(sanitizeNextPath("")).toBe(DEFAULT_AUTH_REDIRECT_PATH);
    expect(sanitizeNextPath("https://evil.example")).toBe(DEFAULT_AUTH_REDIRECT_PATH);
    expect(sanitizeNextPath("//evil.example")).toBe(DEFAULT_AUTH_REDIRECT_PATH);
    expect(sanitizeNextPath("/sign-in?next=/monitors")).toBe(DEFAULT_AUTH_REDIRECT_PATH);
    expect(sanitizeNextPath("/register")).toBe(DEFAULT_AUTH_REDIRECT_PATH);
  });

  it("keeps valid internal next paths", () => {
    expect(sanitizeNextPath("/monitors/abc?tab=events")).toBe("/monitors/abc?tab=events");
    expect(sanitizeNextPath("/runs")).toBe("/runs");
  });

  it("builds sign-in href with sanitized next and optional reason", () => {
    expect(buildSignInHref("/runs", "expired")).toBe("/sign-in?next=%2Fruns&reason=expired");
    expect(buildSignInHref("//external", "unauthenticated")).toBe(
      `/sign-in?next=${encodeURIComponent(DEFAULT_AUTH_REDIRECT_PATH)}&reason=unauthenticated`,
    );
  });
});