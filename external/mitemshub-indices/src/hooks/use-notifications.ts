"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { FreshCallResponse } from "../lib/contracts";
import {
  isNotificationSupported,
  getPermissionStatus,
  requestPermission,
  notifyNewTradePlan,
  notifyTargetHit,
  notifyStopHit,
  notifyEntryFilled,
  notifyGuardianConfirmed,
  notifyGuardianFailing,
} from "../lib/notifications";

export type NotificationPreferences = {
  newTradePlan: boolean;
  targetHit: boolean;
  stopHit: boolean;
  entryFilled: boolean;
  guardianUpdates: boolean;
};

const STORAGE_KEY = "mitems-notification-prefs";
const DEFAULT_PREFS: NotificationPreferences = {
  newTradePlan: true,
  targetHit: true,
  stopHit: true,
  entryFilled: true,
  guardianUpdates: true,
};

function loadPrefs(): NotificationPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...DEFAULT_PREFS };
}

function savePrefs(prefs: NotificationPreferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch { /* ignore */ }
}

/** Snapshot of the call state relevant for detecting changes. */
type CallSnapshot = {
  symbol: string;
  generated_at: string;
  guardian_state: string;
  guardian_reason: string;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  direction_bias: string | null;
  trade_status: string;
  current_close: number | null;
  call: string;
};

function extractSnapshot(call: FreshCallResponse): CallSnapshot {
  return {
    symbol: call.symbol,
    generated_at: call.generated_at,
    guardian_state: call.guardian_state,
    guardian_reason: call.guardian_reason,
    entry: call.entry,
    stop_loss: call.stop_loss,
    take_profit: call.take_profit,
    direction_bias: call.direction_bias,
    trade_status: call.trade_status,
    current_close: call.current_close,
    call: call.call,
  };
}

/**
 * Detect meaningful state transitions between two call snapshots.
 * Returns an array of notification events that should fire.
 */
function detectChanges(
  prev: CallSnapshot | null,
  next: CallSnapshot,
  prefs: NotificationPreferences,
): Array<{ type: string; fire: () => boolean }> {
  if (!prev) return [];

  const events: Array<{ type: string; fire: () => boolean }> = [];
  const { symbol } = next;

  // ── New trade plan generated ─────────────────────────────
  // Detect when a stand_aside transitions to buy/sell candidate
  if (
    prefs.newTradePlan &&
    prev.call === "stand_aside" &&
    next.call !== "stand_aside"
  ) {
    events.push({
      type: "new_trade_plan",
      fire: () =>
        notifyNewTradePlan({
          symbol,
          direction: next.call === "buy_candidate" ? "BUY" : "SELL",
          entry: next.entry,
          confidence: null,
        }),
    });
  }

  // Also notify when a *different* trade plan replaces the previous one
  // (different generated_at means a fresh call was produced)
  if (
    prefs.newTradePlan &&
    prev.generated_at !== next.generated_at &&
    next.call !== "stand_aside" &&
    prev.call !== next.call
  ) {
    events.push({
      type: "new_trade_plan",
      fire: () =>
        notifyNewTradePlan({
          symbol,
          direction: next.call === "buy_candidate" ? "BUY" : "SELL",
          entry: next.entry,
          confidence: null,
        }),
    });
  }

  // ── Guardian state transitions ────────────────────────────
  if (prefs.guardianUpdates && prev.guardian_state !== next.guardian_state) {
    if (next.guardian_state === "confirmed") {
      events.push({
        type: "guardian_confirmed",
        fire: () => notifyGuardianConfirmed({ symbol, reason: next.guardian_reason }),
      });
    } else if (next.guardian_state === "failing") {
      events.push({
        type: "guardian_failing",
        fire: () => notifyGuardianFailing({ symbol, reason: next.guardian_reason }),
      });
    }
  }

  // ── Entry filled detection ─────────────────────────────────
  // Fires when trade_status transitions to "valid" (entry triggered)
  if (
    prefs.entryFilled &&
    prev.trade_status !== "valid" &&
    next.trade_status === "valid" &&
    next.direction_bias
  ) {
    events.push({
      type: "entry_filled",
      fire: () =>
        notifyEntryFilled({
          symbol,
          direction: next.direction_bias!,
          price: next.current_close,
        }),
    });
  }

  // ── Target / stop detection via current price ────────────
  if (prev.entry != null && next.current_close != null && next.direction_bias) {
    const price = next.current_close;
    const direction = next.direction_bias;

    // Target hit: price crossed take_profit level
    if (
      prefs.targetHit &&
      prev.take_profit != null &&
      next.take_profit != null
    ) {
      const crossedTarget =
        (direction === "buy" && price >= next.take_profit) ||
        (direction === "sell" && price <= next.take_profit);
      const wasBelowTarget =
        prev.current_close != null &&
        ((direction === "buy" && prev.current_close < prev.take_profit!) ||
          (direction === "sell" && prev.current_close > prev.take_profit!));

      if (crossedTarget && wasBelowTarget) {
        events.push({
          type: "target_hit",
          fire: () =>
            notifyTargetHit({
              symbol,
              direction,
              price,
              target: next.take_profit,
            }),
        });
      }
    }

    // Stop hit: price crossed stop_loss level
    if (
      prefs.stopHit &&
      prev.stop_loss != null &&
      next.stop_loss != null
    ) {
      const crossedStop =
        (direction === "buy" && price <= next.stop_loss) ||
        (direction === "sell" && price >= next.stop_loss);
      const wasAboveStop =
        prev.current_close != null &&
        ((direction === "buy" && prev.current_close > prev.stop_loss!) ||
          (direction === "sell" && prev.current_close < prev.stop_loss!));

      if (crossedStop && wasAboveStop) {
        events.push({
          type: "stop_hit",
          fire: () =>
            notifyStopHit({
              symbol,
              direction,
              price,
              stop: next.stop_loss,
            }),
        });
      }
    }
  }

  return events;
}

export function useNotifications(currentCall: FreshCallResponse | null) {
  const [prefs, setPrefsState] = useState<NotificationPreferences>(loadPrefs);
  // Always start with "default" to match server render (no Notification API).
  // The real permission is synced in the first useEffect.
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [supported, setSupported] = useState(false);
  const prevCallRef = useRef<CallSnapshot | null>(null);
  const initializedRef = useRef(false);

  // Sync the real permission + support status on mount (client-only).
  useEffect(() => {
    const isSupported = isNotificationSupported();
    setSupported(isSupported);
    if (isSupported) {
      setPermission(getPermissionStatus());
    }
  }, []);

  const setPrefs = useCallback((updater: (prev: NotificationPreferences) => NotificationPreferences) => {
    setPrefsState((prev) => {
      const next = updater(prev);
      savePrefs(next);
      return next;
    });
  }, []);

  const enable = useCallback(async () => {
    if (!isNotificationSupported()) return false;
    const result = await requestPermission();
    setPermission(result);
    return result === "granted";
  }, []);

  const togglePref = useCallback(
    (key: keyof NotificationPreferences) => {
      setPrefs((prev) => ({ ...prev, [key]: !prev[key] }));
    },
    [setPrefs],
  );

  // ── Detect changes and fire notifications ────────────────
  useEffect(() => {
    if (!currentCall) return;

    const snapshot = extractSnapshot(currentCall);

    // Skip the very first call only if it's stand_aside (no active trade).
    // If there's an active trade on mount, we still notify.
    if (!initializedRef.current) {
      initializedRef.current = true;
      prevCallRef.current = snapshot;
      return;
    }

    const events = detectChanges(prevCallRef.current, snapshot, prefs);
    prevCallRef.current = snapshot;

    for (const event of events) {
      event.fire();
    }
  }, [currentCall, prefs]);

  // ── Keep permission state in sync (every 30s — permission changes are rare) ──
  useEffect(() => {
    if (!supported) return;
    const interval = setInterval(() => {
      setPermission(getPermissionStatus());
    }, 30_000);
    return () => clearInterval(interval);
  }, [supported]);

  return {
    permission,
    prefs,
    enable,
    togglePref,
    isSupported: supported,
  };
}
