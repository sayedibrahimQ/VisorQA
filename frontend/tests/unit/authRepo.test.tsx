/**
 * GitHub auth gate + repository selector tests (mocked fetch only).
 * Run: cd frontend && npx vitest run tests/unit/authRepo.test.tsx
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

import { AuthProvider, useAuth } from "@/context/AuthContext";
import { LoginGate } from "@/components/auth/LoginGate";
import { RepoSelector } from "@/components/auth/RepoSelector";

const USER = {
  login: "octocat",
  name: "Octo",
  avatar_url: "https://x/a.png",
  html_url: "https://github.com/octocat",
  auth_mode: "pat",
};

function Probe() {
  const { user, logout } = useAuth();
  return (
    <div>
      <span data-testid="probe-user">{user ? user.login : "anon"}</span>
      <button type="button" onClick={() => void logout()}>
        out
      </button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("GitHub auth flow", () => {
  it("shows the login gate when unauthenticated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })),
    );
    render(
      <AuthProvider>
        <LoginGate />
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("probe-user").textContent).toBe("anon"));
    expect(screen.getByTestId("login-gate")).toBeTruthy();
    expect(screen.getByTestId("login-oauth")).toBeTruthy();
    expect(screen.getByTestId("login-configured")).toBeTruthy();
  });

  it("logs in with the configured App/PAT and exposes the real user", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/api/auth/me")) {
        return { ok: false, status: 401, json: async () => ({}) };
      }
      if (url.includes("/api/auth/github/token")) {
        return { ok: true, status: 200, json: async () => ({ user: USER }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AuthProvider>
        <LoginGate />
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("probe-user").textContent).toBe("anon"));
    fireEvent.click(screen.getByTestId("login-configured"));
    await waitFor(() => expect(screen.getByTestId("probe-user").textContent).toBe("octocat"));
  });
});

describe("RepoSelector", () => {
  it("searches real repositories and selects one", async () => {
    const repos = [
      { full_name: "octocat/visor", name: "visor", owner: "octocat", private: false, default_branch: "main", open_issues_count: 3, updated_at: "", html_url: "" },
      { full_name: "octocat/other", name: "other", owner: "octocat", private: true, default_branch: "dev", open_issues_count: 0, updated_at: "", html_url: "" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => repos })),
    );
    const onSelect = vi.fn();
    render(<RepoSelector selectedRepo={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("repo-selector-toggle"));
    await waitFor(() => expect(screen.getByTestId("repo-option-octocat/visor")).toBeTruthy());
    fireEvent.change(screen.getByTestId("repo-search"), { target: { value: "other" } });
    expect(screen.queryByTestId("repo-option-octocat/visor")).toBeNull();
    fireEvent.click(screen.getByTestId("repo-option-octocat/other"));
    expect(onSelect).toHaveBeenCalledWith("octocat/other");
  });
});
