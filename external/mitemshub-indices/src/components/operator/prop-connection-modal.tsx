"use client";

import React, { useEffect, useState } from "react";
import type { PropConnectionInput } from "../../lib/contracts";

type PropConnectionModalProps = {
  open: boolean;
  initialValue: PropConnectionInput | null;
  onCancel: () => void;
  onConfirm: (value: PropConnectionInput) => void;
};

export function PropConnectionModal({
  open,
  initialValue,
  onCancel,
  onConfirm,
}: PropConnectionModalProps) {
  const [server, setServer] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [startingBalance, setStartingBalance] = useState("5000");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setServer(initialValue?.server ?? "");
    setLogin(initialValue?.login ?? "");
    setPassword(initialValue?.password ?? "");
    setStartingBalance(String(initialValue?.startingBalance ?? 5000));
    setError(null);
  }, [initialValue, open]);

  if (!open) return null;

  const handleSubmit = () => {
    const trimmedServer = server.trim();
    const trimmedLogin = login.trim();
    const trimmedPassword = password.trim();
    const providedCount = [trimmedServer, trimmedLogin, trimmedPassword].filter(Boolean).length;

    if (providedCount > 0 && providedCount < 3) {
      setError("Enter login and password or leave all three fields blank.");
      return;
    }

    onConfirm({
      server: trimmedServer || null,
      login: trimmedLogin || null,
      password: trimmedPassword || null,
      terminalPath: null,
      startingBalance: Number.isNaN(Number(startingBalance)) ? 5000 : Number(startingBalance),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(0,0,0,0.3)] px-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Prop firm connection"
        className="surface w-full max-w-xl rounded-2xl p-6 shadow-[var(--shadow-elevated)]"
      >
        <h2 className="display-serif text-xl font-semibold text-[var(--text-strong)]">
          Prop firm connection
        </h2>
        <p className="mt-2 text-sm leading-6 text-[var(--text-body)]">
          Leave these fields blank to use your own account connection for prop checks.
        </p>

        <div className="mt-5 space-y-4">
          <label className="block">
            <span className="text-xs font-medium text-[var(--text-strong)]">Server</span>
            <input
              value={server}
              onChange={(event) => setServer(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-3.5 py-2 text-sm transition focus:border-[var(--accent-ink)] focus:ring-1 focus:ring-[var(--accent-ink)] outline-none"
              placeholder="e.g. BlueberryMarkets-Demo"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[var(--text-strong)]">Login</span>
            <input
              value={login}
              onChange={(event) => setLogin(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-3.5 py-2 text-sm transition focus:border-[var(--accent-ink)] focus:ring-1 focus:ring-[var(--accent-ink)] outline-none"
              placeholder="e.g. 12345678"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[var(--text-strong)]">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-3.5 py-2 text-sm transition focus:border-[var(--accent-ink)] focus:ring-1 focus:ring-[var(--accent-ink)] outline-none"
              placeholder="Enter your MT5 password"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[var(--text-strong)]">Starting balance</span>
            <input
              value={startingBalance}
              onChange={(event) => setStartingBalance(event.target.value)}
              className="mt-1.5 w-full rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-3.5 py-2 text-sm transition focus:border-[var(--accent-ink)] focus:ring-1 focus:ring-[var(--accent-ink)] outline-none"
            />
          </label>
        </div>

        {error ? (
          <p className="mt-3 text-sm text-[var(--accent-warn)]">{error}</p>
        ) : null}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            className="rounded-xl px-4 py-2 text-sm font-medium text-[var(--text-body)] hover:bg-[var(--bg-surface-hover)] transition"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="primary-action rounded-xl bg-[var(--accent-ink)] px-4 py-2 text-sm font-semibold text-white hover:bg-[var(--accent-ink-hover)]"
            onClick={handleSubmit}
          >
            Continue in prop mode
          </button>
        </div>
      </div>
    </div>
  );
}
