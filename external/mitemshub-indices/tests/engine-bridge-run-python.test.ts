import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";

const ENGINE_ROOT = "c:\\test-engine";
const TEST_SCRIPT = "print('hello')";

type ExecFileCb = (...args: unknown[]) => void;

/**
 * Create a mock execFile where the promisified version returns
 * a fixed stdout/stderr payload on every call.
 */
function makePassingExecFileMock(stdout: string, stderr = "") {
  const promisified = vi.fn(async () => ({ stdout, stderr }));
  const callback = vi.fn() as unknown as { [k: symbol]: unknown };
  (callback as Record<symbol, unknown>)[promisify.custom] = promisified;
  return { callback, promisified };
}

/**
 * Create a mock execFile where every call throws the given error.
 */
function makeFailingExecFileMock(error: Error) {
  const promisified = vi.fn(async () => {
    throw error;
  });
  const callback = vi.fn() as unknown as { [k: symbol]: unknown };
  (callback as Record<symbol, unknown>)[promisify.custom] = promisified;
  return { callback, promisified };
}

/**
 * Import engine-bridge with a mocked node:child_process so that
 * runPythonScript uses our execFile mock instead of real I/O.
 */
async function importBridgeWithMock(
  execFileMock: { [k: symbol]: unknown } & ((...args: unknown[]) => void),
) {
  vi.doMock("node:child_process", () => ({
    execFile: execFileMock,
    default: { execFile: execFileMock },
  }));
  vi.resetModules();
  return await import("../src/lib/engine-bridge");
}

// ────────────────────────────────────────────────────────────

describe("runPythonScript", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
    vi.doUnmock("node:child_process");
  });

  // ── Happy path ──────────────────────────────────────────────

  it("returns stdout, stderr and durationMs on success", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    const result = await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
      label: "happy",
    });

    expect(result.stdout).toBe("OK");
    expect(result.stderr).toBe("");
    expect(result.durationMs).toBeGreaterThanOrEqual(0);

    // First candidate is "python"
    expect(promisified).toHaveBeenCalledWith(
      "python",
      ["-c", TEST_SCRIPT],
      expect.objectContaining({
        cwd: ENGINE_ROOT,
        timeout: 5000,
        windowsHide: true,
      }),
    );
  });

  // ── stderr capture ──────────────────────────────────────────

  it("logs stderr to console.error when the subprocess produces stderr on success", async () => {
    const { callback } = makePassingExecFileMock("OK", "ImportWarning: numpy");
    const bridge = await importBridgeWithMock(callback);
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const result = await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
      label: "stderr-test",
    });

    expect(result.stderr).toBe("ImportWarning: numpy");
    // Should have logged it for the pipeline diagnostics
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("stderr-test"),
      "ImportWarning: numpy",
    );
  });

  it("logs stderr from a failed subprocess attempt", async () => {
    const { callback, promisified } = makeFailingExecFileMock(
      Object.assign(new Error("exec failed"), { stderr: "ModuleNotFoundError: numpy" }),
    );

    const bridge = await importBridgeWithMock(callback);
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await expect(
      bridge.__testRunPythonScript({
        engineRoot: ENGINE_ROOT,
        pythonScript: TEST_SCRIPT,
        timeout: 5000,
      }),
    ).rejects.toThrow();

    // Even though both candidates failed, the first attempt's stderr
    // should have been logged before the throw.
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("python"),
      "ModuleNotFoundError: numpy",
    );
  });

  // ── Candidate iteration fallback ────────────────────────────

  it("falls back to py -3 when python fails", async () => {
    let callCount = 0;
    const promisified = vi.fn(async (...args: unknown[]) => {
      callCount += 1;
      if (callCount === 1) {
        // First call (python) fails
        throw new Error("python not found");
      }
      // Second call (py -3) succeeds
      return { stdout: "OK", stderr: "" };
    });
    const callback = vi.fn() as unknown as { [k: symbol]: unknown };
    (callback as Record<symbol, unknown>)[promisify.custom] = promisified;

    const bridge = await importBridgeWithMock(callback);

    const result = await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
    });

    expect(result.stdout).toBe("OK");
    expect(promisified).toHaveBeenCalledTimes(2);
    // First call used "python"
    expect(promisified.mock.calls[0][0]).toBe("python");
    // Second call used "py" with args "-3"
    expect(promisified.mock.calls[1][0]).toBe("py");
    expect(promisified.mock.calls[1][1]).toEqual(["-3", "-c", TEST_SCRIPT]);
  });

  it("uses SYNTHETIC_ENGINE_PYTHON exclusively when set, skipping default candidates", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_PYTHON", "C:\\Python39\\python.exe");

    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
    });

    // Only one attempt with the configured python
    expect(promisified).toHaveBeenCalledTimes(1);
    expect(promisified).toHaveBeenCalledWith(
      "C:\\Python39\\python.exe",
      ["-c", TEST_SCRIPT],
      expect.any(Object),
    );
  });

  // ── All candidates exhausted ────────────────────────────────

  it("throws the last error when all candidates fail", async () => {
    const promisified = vi.fn(async () => {
      throw new Error("last_error_detail");
    });
    const callback = vi.fn() as unknown as { [k: symbol]: unknown };
    (callback as Record<symbol, unknown>)[promisify.custom] = promisified;

    const bridge = await importBridgeWithMock(callback);

    await expect(
      bridge.__testRunPythonScript({
        engineRoot: ENGINE_ROOT,
        pythonScript: TEST_SCRIPT,
        timeout: 5000,
      }),
    ).rejects.toThrow("last_error_detail");

    // Should have tried both candidates
    expect(promisified).toHaveBeenCalledTimes(2);
  });

  // ── Timeout propagation ────────────────────────────────────

  it("passes the timeout value to execFile options", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 42_000,
    });

    expect(promisified.mock.calls[0][2]).toMatchObject({ timeout: 42_000 });
  });

  // ── Signal cancellation ────────────────────────────────────

  it("passes AbortSignal to execFile options", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);
    const ac = new AbortController();

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
      signal: ac.signal,
    });

    expect(promisified.mock.calls[0][2]).toMatchObject({
      signal: ac.signal,
    });
  });

  // ── extraEnv merging ────────────────────────────────────────

  it("merges extraEnv with the safe child environment", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
      extraEnv: {
        MY_CUSTOM_VAR: "custom_value",
        ANOTHER_VAR: "123",
      },
    });

    const env = promisified.mock.calls[0][2].env as Record<string, string>;

    // PYTHONPATH should be set from engineRoot
    expect(env.PYTHONPATH).toBe(join(ENGINE_ROOT, "src"));
    // PYTHONDONTWRITEBYTECODE should be set
    expect(env.PYTHONDONTWRITEBYTECODE).toBe("1");
    // Custom extraEnv vars should be present
    expect(env.MY_CUSTOM_VAR).toBe("custom_value");
    expect(env.ANOTHER_VAR).toBe("123");
  });

  it("does not include extraEnv vars that are not explicitly passed", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
    });

    const env = promisified.mock.calls[0][2].env as Record<string, string>;

    // Default vars are present
    expect(env.PYTHONPATH).toBe(join(ENGINE_ROOT, "src"));
    expect(env.PYTHONDONTWRITEBYTECODE).toBe("1");
    // No custom vars leaked
    expect(env.MY_CUSTOM_VAR).toBeUndefined();
  });

  // ── validatePythonImport option ─────────────────────────────

  it("throws early when validatePythonImport check fails", async () => {
    const { callback, promisified } = makePassingExecFileMock("FAIL", ""); // Not "OK"
    const bridge = await importBridgeWithMock(callback);

    await expect(
      bridge.__testRunPythonScript({
        engineRoot: ENGINE_ROOT,
        pythonScript: TEST_SCRIPT,
        timeout: 5000,
        label: "validate-test",
        validatePythonImport: "from missing.module import something",
      }),
    ).rejects.toThrow(
      /import validation failed.*from missing\.module import something/,
    );
  });

  it("runs the main script when validatePythonImport check passes", async () => {
    let callIdx = 0;
    const promisified = vi.fn(async () => {
      callIdx += 1;
      // First call: import check
      if (callIdx === 1) return { stdout: "OK\n", stderr: "" };
      // Second call: main script
      return { stdout: "done", stderr: "" };
    });
    const callback = vi.fn() as unknown as { [k: symbol]: unknown };
    (callback as Record<symbol, unknown>)[promisify.custom] = promisified;

    const bridge = await importBridgeWithMock(callback);

    const result = await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: "print('main')",
      timeout: 5000,
      validatePythonImport: "from my_module import MyClass",
    });

    expect(result.stdout).toBe("done");
    // First call validates import, second runs the main script
    expect(promisified).toHaveBeenCalledTimes(2);
    // The script string is the last element in the args array
    const importScript = (promisified.mock.calls[0][1] as string[]).at(-1) ?? "";
    const mainScript = (promisified.mock.calls[1][1] as string[]).at(-1) ?? "";
    expect(importScript).toContain("import MyClass");
    expect(mainScript).toContain("print('main')");
  });

  // ── Environment hygiene ─────────────────────────────────────

  it("does not leak arbitrary process.env into subprocess environment", async () => {
    const { callback, promisified } = makePassingExecFileMock("OK", "");
    const bridge = await importBridgeWithMock(callback);

    await bridge.__testRunPythonScript({
      engineRoot: ENGINE_ROOT,
      pythonScript: TEST_SCRIPT,
      timeout: 5000,
    });

    const env = promisified.mock.calls[0][2].env as Record<string, string>;

    // Approved vars are present
    expect(env.PATH).toBeDefined();
    expect(env.NODE_ENV).toBeDefined();
    // Sensible vars are NOT present
    expect(env.SECRET_API_KEY).toBeUndefined();
    expect(env.DATABASE_URL).toBeUndefined();
  });
});
