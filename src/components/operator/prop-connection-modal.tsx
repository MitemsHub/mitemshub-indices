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
  const [startingBalance, setStartingBalance] = useState("100000");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    setServer(initialValue?.server ?? "");
    setLogin(initialValue?.login ?? "");
    setPassword(initialValue?.password ?? "");
    setStartingBalance(String(initialValue?.startingBalance ?? 100000));
    setError(null);
  }, [initialValue, open]);

  if (!open) {
    return null;
  }

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
      startingBalance: Number(startingBalance) || 100000,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(15,23,42,0.18)] px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Prop firm connection"
        className="surface w-full max-w-xl rounded-[2rem] p-6"
      >
        <h2 className="text-2xl font-semibold text-[var(--text-strong)]">
          Prop firm connection
        </h2>
        <p className="mt-3 text-sm leading-6 text-[var(--text-body)]">
          Leave these fields blank to use your own account connection for prop
          checks.
        </p>
        <label className="mt-5 block text-sm font-medium text-[var(--text-strong)]">
          Server
          <input
            value={server}
            onChange={(event) => setServer(event.target.value)}
            className="mt-2 w-full rounded-xl border border-[rgba(15,23,42,0.12)] bg-white px-3 py-2"
          />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Login
          <input
            value={login}
            onChange={(event) => setLogin(event.target.value)}
            className="mt-2 w-full rounded-xl border border-[rgba(15,23,42,0.12)] bg-white px-3 py-2"
          />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full rounded-xl border border-[rgba(15,23,42,0.12)] bg-white px-3 py-2"
          />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Starting balance
          <input
            value={startingBalance}
            onChange={(event) => setStartingBalance(event.target.value)}
            className="mt-2 w-full rounded-xl border border-[rgba(15,23,42,0.12)] bg-white px-3 py-2"
          />
        </label>
        {error ? (
          <p className="mt-4 text-sm text-[var(--accent-warn)]">{error}</p>
        ) : null}
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            className="rounded-xl px-4 py-2 text-sm text-[var(--text-body)]"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="command-button rounded-xl px-4 py-2 text-sm font-semibold"
            onClick={handleSubmit}
          >
            Continue in prop mode
          </button>
        </div>
      </div>
    </div>
  );
}
