"use client";

import React, { useState } from "react";
import { Github, KeyRound, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

/** Darkroom sign-in screen shown when no GitHub session exists. */
export function LoginGate() {
  const { loginWithOAuth, loginWithConfigured, loginWithToken, error } = useAuth();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div
      data-testid="login-gate"
      className="flex min-h-[60vh] items-center justify-center px-4"
    >
      <div className="w-full max-w-sm rounded-lg border border-border-subtle bg-surface p-6 shadow-2xl">
        <div className="flex items-center gap-2">
          <Github className="h-6 w-6 text-text-primary" aria-hidden="true" />
          <h2 className="font-display text-lg font-semibold text-text-primary">
            Sign in with GitHub
          </h2>
        </div>
        <p className="mt-2 text-sm leading-6 text-text-secondary">
          VisorQA scopes every run, screenshot, and action to a repository you
          choose. Sign in to load your real repositories and pull requests.
        </p>

        <button
          type="button"
          data-testid="login-oauth"
          onClick={loginWithOAuth}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-md bg-text-primary px-4 py-2.5 text-sm font-semibold text-canvas transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
        >
          <Github className="h-4 w-4" aria-hidden="true" />
          Continue with GitHub (OAuth)
        </button>

        <button
          type="button"
          data-testid="login-configured"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await loginWithConfigured();
            } finally {
              setBusy(false);
            }
          }}
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-md border border-border-strong px-4 py-2.5 text-sm text-text-primary transition-colors hover:border-neural-pulse/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <KeyRound className="h-4 w-4" />}
          Use Configured GitHub App / PAT
        </button>

        <form
          className="mt-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!token.trim()) return;
            setBusy(true);
            try {
              await loginWithToken(token.trim());
              setToken("");
            } catch {
              /* error surfaces below */
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="pat-input" className="font-mono text-[11px] text-text-muted">
            Personal Access Token
          </label>
          <input
            id="pat-input"
            data-testid="login-pat-input"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="ghp_…"
            className="mt-1 w-full rounded-md border border-border-subtle bg-canvas px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
          />
          <button
            type="submit"
            data-testid="login-pat-submit"
            disabled={busy || !token.trim()}
            className="mt-2 w-full rounded-md border border-border-subtle px-4 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus disabled:opacity-50"
          >
            Sign in with Token
          </button>
        </form>

        {error ? (
          <p data-testid="login-error" role="alert" className="mt-3 text-xs leading-5 text-defect-crimson">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
