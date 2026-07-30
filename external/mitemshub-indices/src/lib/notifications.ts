/**
 * Browser push notification utility.
 *
 * Uses the native Notification API (not service-worker push). This gives us:
 *  - Instant in-app alerts without a backend push server
 *  - Works on both desktop and mobile browsers that support Notification
 *  - Graceful degradation when permission is denied or unsupported
 *
 * For trade-plan alerts we only need the page to be open — the user is
 * actively monitoring the dashboard, so page-level notifications are ideal.
 */

export type NotificationPermission = "granted" | "denied" | "default";

export type NotificationType =
  | "new_trade_plan"
  | "target_hit"
  | "stop_hit"
  | "entry_filled"
  | "plan_invalidated"
  | "guardian_confirmed"
  | "guardian_failing";

// ── Permission management ──────────────────────────────────────

/** Check whether the browser supports the Notification API. */
export function isNotificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** Return the current permission state without prompting. */
export function getPermissionStatus(): NotificationPermission {
  if (!isNotificationSupported()) return "denied";
  return Notification.permission as NotificationPermission;
}

/** Request notification permission from the user. Returns the resulting state. */
export async function requestPermission(): Promise<NotificationPermission> {
  if (!isNotificationSupported()) return "denied";
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  return await Notification.requestPermission();
}

// ── Notification sending ───────────────────────────────────────

const ICON_PATH = "/favicon.ico";

interface NotificationOptions {
  title: string;
  body: string;
  tag?: string; // dedup key — same tag replaces previous notification
  renotify?: boolean; // vibrate + re-alert even for same tag
  icon?: string;
  silent?: boolean;
}

/**
 * Send a browser notification. Returns `true` if it was shown, `false` if
 * permission was denied or the API is unavailable.
 */
export function sendNotification(opts: NotificationOptions): boolean {
  if (!isNotificationSupported()) return false;
  if (Notification.permission !== "granted") return false;

  try {
    new Notification(opts.title, {
      body: opts.body,
      icon: opts.icon ?? ICON_PATH,
      tag: opts.tag ?? "mitems-default",
      renotify: opts.renotify ?? true,
      silent: opts.silent ?? false,
    } as NotificationOptions & { renotify?: boolean });
    return true;
  } catch {
    // Some mobile browsers throw when creating notifications from
    // a service worker context or when the page isn't focused.
    return false;
  }
}

// ── Convenience helpers per notification type ───────────────────

function formatPrice(price: number | null): string {
  if (price == null) return "—";
  return price.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function notifyNewTradePlan(params: {
  symbol: string;
  direction: string;
  entry: number | null;
  confidence: number | null;
}): boolean {
  const dir = params.direction.toUpperCase();
  const conf = params.confidence != null
    ? ` (${(params.confidence * 100).toFixed(0)}% confidence)`
    : "";
  return sendNotification({
    title: `📈 New ${dir} Trade Plan — ${params.symbol}`,
    body: `Entry: ${formatPrice(params.entry)}${conf}`,
    tag: `trade-plan-${params.symbol}-${Date.now()}`,
    renotify: true,
  });
}

export function notifyTargetHit(params: {
  symbol: string;
  direction: string;
  price: number | null;
  target: number | null;
}): boolean {
  return sendNotification({
    title: `🎯 TARGET HIT — ${params.symbol}`,
    body: `${params.direction.toUpperCase()} target reached at ${formatPrice(params.price)} (target: ${formatPrice(params.target)})`,
    tag: `target-hit-${params.symbol}`,
    renotify: true,
  });
}

export function notifyStopHit(params: {
  symbol: string;
  direction: string;
  price: number | null;
  stop: number | null;
}): boolean {
  return sendNotification({
    title: `🛑 STOP HIT — ${params.symbol}`,
    body: `${params.direction.toUpperCase()} stop triggered at ${formatPrice(params.price)} (stop: ${formatPrice(params.stop)})`,
    tag: `stop-hit-${params.symbol}`,
    renotify: true,
  });
}

export function notifyEntryFilled(params: {
  symbol: string;
  direction: string;
  price: number | null;
}): boolean {
  return sendNotification({
    title: `✅ Entry Filled — ${params.symbol}`,
    body: `${params.direction.toUpperCase()} position entered at ${formatPrice(params.price)}`,
    tag: `entry-filled-${params.symbol}`,
    renotify: true,
  });
}

export function notifyGuardianConfirmed(params: {
  symbol: string;
  reason: string;
}): boolean {
  return sendNotification({
    title: `🟢 Guardian Confirmed — ${params.symbol}`,
    body: params.reason,
    tag: `guardian-confirmed-${params.symbol}`,
    renotify: true,
  });
}

export function notifyGuardianFailing(params: {
  symbol: string;
  reason: string;
}): boolean {
  return sendNotification({
    title: `🔴 Guardian Failing — ${params.symbol}`,
    body: params.reason,
    tag: `guardian-failing-${params.symbol}`,
    renotify: true,
  });
}

export function notifyGuardianCancelled(params: {
  symbol: string;
  reason: string;
}): boolean {
  return sendNotification({
    title: `⛔ Guardian Cancelled — ${params.symbol}`,
    body: params.reason,
    tag: `guardian-cancelled-${params.symbol}`,
    renotify: true,
  });
}

export function notifyGuardianActionable(params: {
  symbol: string;
  reason: string;
}): boolean {
  return sendNotification({
    title: `🟡 Guardian Actionable — ${params.symbol}`,
    body: params.reason,
    tag: `guardian-actionable-${params.symbol}`,
    renotify: true,
  });
}

export function notifyBridgeReconnected(): boolean {
  return sendNotification({
    title: `🟢 Bridge Reconnected`,
    body: `Intelligence panels updating — fresh market data incoming.`,
    tag: `bridge-reconnected`,
    renotify: true,
  });
}
