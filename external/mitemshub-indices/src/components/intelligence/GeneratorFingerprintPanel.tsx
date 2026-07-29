"use client";

import { useCallback, useState } from "react";

type GeneratorFingerprint = {
  detected_index: number;
  detected_label: string;
  confidence: number;
  kurtosis: number;
  skewness: number;
  cluster_score: number;
} | null;

type CalibrateResult = {
  success: boolean;
  symbol: string;
  convergence: boolean;
  observations: number;
  omega: number;
  alpha: number;
  beta: number;
  gamma: number;
  persistence: number;
  half_life: number;
  long_run_vol: number;
  realized_vol: number;
  vol_ratio: number;
  saved_path: string | null;
  error: string | null;
  duration_ms: number;
};

function formatNum(v: number, decimals = 4): string {
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(decimals);
}

export default function GeneratorFingerprintPanel({
  data,
  loading,
}: {
  data: GeneratorFingerprint | null;
  loading?: boolean;
}) {
  const [calibrating, setCalibrating] = useState(false);
  const [calibrateResult, setCalibrateResult] = useState<CalibrateResult | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState("R_100");

  // Clear calibration result when switching symbols
  const handleSymbolChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSymbol(e.target.value);
    setCalibrateResult(null);
  }, []);

  const handleCalibrate = useCallback(async () => {
    setCalibrating(true);
    setCalibrateResult(null);
    try {
      const res = await fetch("/api/system/calibrate-egarch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: selectedSymbol }),
      });
      const result: CalibrateResult = await res.json();
      setCalibrateResult(result);
    } catch (err) {
      setCalibrateResult({
        success: false,
        symbol: selectedSymbol,
        convergence: false,
        observations: 0,
        omega: 0,
        alpha: 0,
        beta: 0,
        gamma: 0,
        persistence: 0,
        half_life: 0,
        long_run_vol: 0,
        realized_vol: 0,
        vol_ratio: 0,
        saved_path: null,
        error: err instanceof Error ? err.message : "Network error",
        duration_ms: 0,
      });
    } finally {
      setCalibrating(false);
    }
  }, [selectedSymbol]);

  if (loading) {
    return (
      <div className="p-4 rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel)]">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-[var(--accent-ink)] animate-pulse" />
          <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
            Generator Fingerprint
          </span>
        </div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-4 rounded bg-[var(--bg-panel-muted)] animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel)]">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div
          className={`w-2 h-2 rounded-full ${
            data ? "bg-[var(--accent-positive)]" : "bg-[var(--text-muted)]"
          }`}
        />
        <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
          Generator Fingerprint
        </span>
      </div>

      {/* Fingerprint data */}
      {data ? (
        <div className="space-y-3">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold text-[var(--text-strong)]">
              {data.detected_label}
            </span>
            <span className="text-xs text-[var(--text-muted)]">
              {(data.confidence * 100).toFixed(0)}% confidence
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-[var(--text-muted)]">Kurtosis</div>
              <div className="font-mono text-[var(--text-body)]">{formatNum(data.kurtosis, 2)}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">Skewness</div>
              <div className="font-mono text-[var(--text-body)]">{formatNum(data.skewness, 4)}</div>
            </div>
            <div>
              <div className="text-[var(--text-muted)]">Cluster</div>
              <div className="font-mono text-[var(--text-body)]">{formatNum(data.cluster_score, 4)}</div>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-[var(--text-muted)] italic">
          No fingerprint data — waiting for market data.
        </p>
      )}

      {/* Divider */}
      <div className="my-4 border-t border-[var(--line-subtle)]" />

      {/* Calibrate EGARCH section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
            EGARCH Calibration
          </span>
          {calibrateResult?.success && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent-positive-soft)] text-[var(--accent-positive)]">
              ✓ Calibrated
            </span>
          )}
        </div>

        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
          Fit EGARCH(1,1) parameters to real tick data. The calibrated params
          are auto-loaded on next engine start, replacing default priors.
        </p>

        <div className="flex items-center gap-2">
          <select
            value={selectedSymbol}
            onChange={handleSymbolChange}
            className="flex-1 px-2 py-1.5 text-xs rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] text-[var(--text-body)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-ink)]"
          >
            <option value="R_75">Volatility 75 (R_75)</option>
            <option value="R_100">Volatility 100 (R_100)</option>
          </select>

          <button
            onClick={handleCalibrate}
            disabled={calibrating}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-[var(--accent-ink)] bg-[var(--accent-ink)] text-white hover:bg-[var(--accent-ink-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {calibrating ? (
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                Fitting…
              </span>
            ) : (
              "Calibrate EGARCH"
            )}
          </button>
        </div>

        {/* Calibration result */}
        {calibrateResult && (
          <div
            className={`p-3 rounded-lg text-xs space-y-2 ${
              calibrateResult.success && calibrateResult.convergence
                ? "bg-[var(--accent-positive-soft)] border border-[var(--accent-positive)]"
                : calibrateResult.success && !calibrateResult.convergence
                ? "bg-[var(--accent-warn-soft)] border border-[var(--accent-warn)]"
                : "bg-[var(--accent-danger-soft)] border border-[var(--accent-danger)]"
            }`}
          >
            {calibrateResult.success && calibrateResult.convergence ? (
              <>
                <div className="font-medium text-[var(--accent-positive)]">
                  Calibration converged ({calibrateResult.observations} observations, {calibrateResult.duration_ms}ms)
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] font-mono text-[var(--text-body)]">
                  <div>ω = {formatNum(calibrateResult.omega, 6)}</div>
                  <div>α = {formatNum(calibrateResult.alpha, 4)}</div>
                  <div>β = {formatNum(calibrateResult.beta, 4)}</div>
                  <div>γ = {formatNum(calibrateResult.gamma, 4)}</div>
                  <div>persistence = {formatNum(calibrateResult.persistence, 4)}</div>
                  <div>half-life = {calibrateResult.half_life.toFixed(1)} obs</div>
                  <div>long-run vol = {formatNum(calibrateResult.long_run_vol, 6)}</div>
                  <div>vol ratio = {formatNum(calibrateResult.vol_ratio, 4)}</div>
                </div>
                {calibrateResult.saved_path && (
                  <div className="text-[10px] text-[var(--text-muted)]">
                    Saved: {calibrateResult.saved_path}
                  </div>
                )}
              </>
            ) : calibrateResult.success && !calibrateResult.convergence ? (
              <div className="font-medium text-[var(--accent-warn)]">
                Optimization did not converge: {calibrateResult.error ?? "Unknown reason"}
              </div>
            ) : (
              <div className="font-medium text-[var(--accent-danger)]">
                Calibration failed: {calibrateResult.error ?? "Unknown error"}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
