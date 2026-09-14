"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { ErrorState, LoadingState, Panel } from "@/components/ui";
import { AUTH_SESSION_QUERY_KEY, setAuthSessionUser, useAuthSession } from "@/hooks/auth";
import { sanitizeNextPath } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useAuthSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const searchParams = typeof window === "undefined" ? null : new URLSearchParams(window.location.search);
  const nextPath = sanitizeNextPath(searchParams?.get("next"));

  useEffect(() => {
    if (!session.isLoading && session.data) {
      router.replace(nextPath);
    }
  }, [nextPath, router, session.data, session.isLoading]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const response = await api.register({
        email,
        password,
        display_name: displayName || undefined,
      });
      setAuthSessionUser(queryClient, response);
      await queryClient.invalidateQueries({ queryKey: AUTH_SESSION_QUERY_KEY });
      router.replace(nextPath);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Unable to create account right now.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (session.isLoading) {
    return <LoadingState label="Checking session…" />;
  }

  return (
    <div className="mx-auto max-w-md">
      <Panel className="p-6">
        <p className="text-xs uppercase tracking-[0.18em] text-argus-muted">ARGUS Account</p>
        <h1 className="mt-2 text-xl font-semibold">Create account</h1>
        <p className="mt-2 text-sm text-argus-muted">Create an ARGUS account to run private monitor workflows.</p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <label className="block text-xs text-argus-muted">
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="argus-field mt-1 w-full"
              autoComplete="email"
              required
            />
          </label>

          <label className="block text-xs text-argus-muted">
            Display name (optional)
            <input
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="argus-field mt-1 w-full"
              autoComplete="name"
            />
          </label>

          <label className="block text-xs text-argus-muted">
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="argus-field mt-1 w-full"
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>

          {error ? <ErrorState detail={error} /> : null}

          <button type="submit" className="argus-control w-full justify-center" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-4 text-xs text-argus-muted">
          Already have an account?{" "}
          <Link href={`/sign-in?next=${encodeURIComponent(nextPath)}`} className="text-argus-accent underline underline-offset-2">
            Sign in
          </Link>
          .
        </p>
      </Panel>
    </div>
  );
}