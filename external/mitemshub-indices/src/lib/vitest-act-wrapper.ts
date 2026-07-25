/**
 * vitest-act-wrapper.ts — Vitest setup file
 *
 * Auto-wraps every `it()` / `test()` block in React's `act()`, silencing
 * the "An update to X inside a test was not wrapped in act(...)" warnings
 * at the framework level instead of fixing them one-by-one.
 *
 * Works by installing a Proxy on `globalThis.it` and `globalThis.test`
 * that intercepts the test-function argument and wraps it with `act()`.
 * All modifiers (`.only`, `.skip`, `.each`, `.todo`, `.fails`) are
 * transitively wrapped via the Proxy's `get` trap.
 *
 * This module is registered in vitest.config.ts via `setupFiles`.
 */

import { act } from "@testing-library/react";

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Return a modified version of `fn` that wraps the last function
 * argument (the test body) in React's `act()`.
 *
 * Handles both sync and async test bodies, `it.each` parameterised
 * tests (where the function receives `innerArgs`), and the three-arg
 * `it(name, fn, timeout?)` signature.
 */
function withAct<T extends (...args: unknown[]) => unknown>(fn: T): T {
  return ((...args: unknown[]) => {
    // Find the last argument that is a function — that's the test body.
    // For `it(name, fn)` → args[1]; for `it.each(...)(name, fn)` → args[1].
    for (let i = args.length - 1; i >= 0; i--) {
      if (typeof args[i] === "function") {
        const originalImpl = args[i] as (...innerArgs: unknown[]) => unknown;
        args[i] = async (...innerArgs: unknown[]) => {
          await act(async () => {
            await originalImpl(...innerArgs);
          });
        };
        break;
      }
    }
    return fn(...args);
  }) as T;
}

/**
 * Build a Proxy that wraps the callable AND all its method properties
 * (`.only`, `.skip`, `.each`, `.todo`, `.fails`, `.concurrent`, etc.)
 * with `withAct`, ensuring every test body goes through `act()`.
 */
function wrapWithAct<T extends (...args: unknown[]) => unknown>(original: T): T {
  return new Proxy(original, {
    // Handle direct calls: `it("name", fn)` or `test("name", fn)`
    apply(target, thisArg, args) {
      const result = Reflect.apply(withAct(target), thisArg, args);
      // Proxy return values that are functions — this covers `it.each([...])`
      // which returns a callable `(name, fn) => void` that needs wrapping too.
      return typeof result === "function" ? wrapWithAct(result as (...args: unknown[]) => unknown) : result;
    },
    // Handle method calls: `it.only("name", fn)`, `it.skip("name", fn)`, etc.
    // Also handles `it.each(...)` which returns another callable.
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      // Only wrap functions — skip non-function properties
      if (typeof value === "function") {
        // Create a proxy for the method too, so chained calls like
        // `it.each([1, 2]).only("test", fn)` still get wrapped.
        return wrapWithAct(value as (...args: unknown[]) => unknown);
      }
      return value;
    },
  }) as unknown as T;
}

// ── Install global proxies ──────────────────────────────────────

// Vitest injects `it`, `test`, `describe` etc. when `globals: true`.
// The setup file runs after these globals are installed but before
// any test file executes, so `globalThis.it` is already defined.

(globalThis as Record<string, unknown>).it = wrapWithAct(
  (globalThis as Record<string, unknown>).it as (...args: unknown[]) => unknown,
);

(globalThis as Record<string, unknown>).test = wrapWithAct(
  (globalThis as Record<string, unknown>).test as (...args: unknown[]) => unknown,
);
