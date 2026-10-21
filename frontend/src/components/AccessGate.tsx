import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";

import { fetchAccessStatus, unlockSite } from "../api/client";

type GateState = "loading" | "open" | "locked";

/**
 * Shared-password gate for shared/public deployments.
 *
 * The gate is invisible during normal local use: when SITE_PASSWORD is empty
 * the status endpoint reports `authenticated: true` and the app renders as
 * usual. When it is set, the app stays hidden until the access code is
 * accepted and the signed session cookie is stored.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>("loading");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    try {
      const status = await fetchAccessStatus();
      setState(status.authenticated ? "open" : "locked");
    } catch {
      // If the API is unreachable, let the app show its own connection error
      // instead of trapping the user on a gate screen that cannot work.
      setState("open");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    const onUnauthorized = () => {
      setError("Your session expired. Enter the access code again.");
      setState("locked");
    };
    window.addEventListener("scholaris:unauthorized", onUnauthorized);
    return () => window.removeEventListener("scholaris:unauthorized", onUnauthorized);
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await unlockSite(code);
      setCode("");
      setState("open");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not unlock this site.");
    } finally {
      setBusy(false);
    }
  };

  if (state === "open") {
    return <>{children}</>;
  }

  return (
    <div className="gate-screen">
      <form className="gate-card" onSubmit={handleSubmit}>
        <p className="eyebrow">Private access</p>
        <h1>Scholaris</h1>
        <p className="page-subtitle">Enter the access code to continue.</p>

        {state === "loading" ? (
          <p className="gate-status">Checking access…</p>
        ) : (
          <>
            <div className="field">
              <label htmlFor="access-code">Access code</label>
              <input
                id="access-code"
                className="input"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="Shared access code"
              />
            </div>
            {error ? (
              <p className="gate-error" role="alert">
                {error}
              </p>
            ) : null}
            <button
              className="btn btn-primary btn-large"
              type="submit"
              disabled={busy || !code.trim()}
            >
              {busy ? "Checking…" : "Unlock"}
            </button>
          </>
        )}

        <p className="gate-hint">Ask the site owner for the code.</p>
      </form>
    </div>
  );
}
