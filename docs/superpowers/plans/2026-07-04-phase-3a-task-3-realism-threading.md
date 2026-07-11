# Phase 3A Task 3 Realism Threading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add integration coverage for realism settings in backtest artifacts and CLI/runtime flows, then thread `config.paper` through those paths with the smallest possible code change.

**Architecture:** Keep the existing `PaperExecutionConfig` and `PaperBroker` behavior intact, and only connect already-defined realism settings into backtest, live paper, and CLI entry points. Extend the backtest artifact payload with a serialized `paper` section and verify CLI plumbing by asserting forwarded config values and artifact contents instead of broad refactors.

**Tech Stack:** Python 3.11+, `unittest`, `dataclasses.replace`, existing CLI/backtest/live modules, JSON artifacts

---

## File Structure

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_execution_realism.py`
  - Add failing integration tests for backtest artifact realism fields and CLI/live config forwarding.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`
  - Extend artifact expectations for backtest JSON output when realism flags are provided through the CLI.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\backtest\engine.py`
  - Pass `config.paper` into `PaperBroker` and include serialized paper settings in artifact payloads.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Pass `cfg.paper` into `PaperBroker`.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add minimal realism flags for `backtest` and `paper-live`, construct an updated `TraderConfig`, and pass it into the runtime entry points.

### Task 1: Add Failing Integration Tests

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_execution_realism.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`

- [ ] **Step 1: Write the failing backtest artifact integration test**

```python
def test_backtest_artifact_records_paper_realism_settings(self) -> None:
    config = replace(
        TraderConfig.default(),
        paper=PaperExecutionConfig(exit_slippage_ticks=0.5, execution_penalty_per_trade=0.2),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "backtest.json"
        BacktestEngine(config=config).run_ticks(
            synthetic_ticks(),
            symbol="R_75",
            timeframe_sec=60,
            artifact_output_path=output,
        )
        payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["paper"]["exit_slippage_ticks"] == 0.5
    assert payload["paper"]["execution_penalty_per_trade"] == 0.2
```

- [ ] **Step 2: Write the failing CLI/runtime forwarding tests**

```python
def test_backtest_cli_builds_paper_realism_config(self) -> None:
    with patch("synthetic_trader.cli.BacktestEngine") as engine_cls:
        engine = engine_cls.return_value
        engine.run_ticks.return_value = SimpleNamespace(
            metrics=SimpleNamespace(trades=0, win_rate=0.0, profit_factor=0.0, expectancy_r=0.0, net_pnl=0.0),
            signals=0,
            rejected_signals=0,
            final_equity=1000.0,
            model_version="unit-test",
        )
        exit_code = main(["backtest", "--csv", str(csv_path), "--exit-slippage-ticks", "0.5", "--execution-penalty", "0.2"])

    config = engine_cls.call_args.kwargs["config"]
    assert exit_code == 0
    assert config.paper.exit_slippage_ticks == 0.5
    assert config.paper.execution_penalty_per_trade == 0.2
```

```python
def test_paper_live_cli_builds_paper_realism_config(self) -> None:
    summary = LivePaperSummary(...)
    with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
        exit_code = main(["paper-live", "--exit-slippage-ticks", "0.25", "--execution-penalty", "0.1"])

    config = mocked_run.call_args.kwargs["config"]
    assert exit_code == 0
    assert config.paper.exit_slippage_ticks == 0.25
    assert config.paper.execution_penalty_per_trade == 0.1
```

- [ ] **Step 3: Run the focused tests to verify they fail**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_reporting -v`
Expected: failures because the backtest artifact lacks `paper`, and the CLI parser rejects the realism flags or does not pass `config`.

### Task 2: Implement Minimal Threading

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\backtest\engine.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`

- [ ] **Step 1: Pass realism config into the backtest broker and artifact payload**

```python
broker = PaperBroker(config.paper)
```

```python
if artifact_output_path is not None:
    dump_json_file(
        artifact_output_path,
        {
            **to_json_ready(result),
            "paper": asdict(config.paper),
        },
    )
```

- [ ] **Step 2: Pass realism config into the live paper broker**

```python
broker = PaperBroker(cfg.paper)
```

- [ ] **Step 3: Add CLI realism flags and build a minimally updated config**

```python
backtest.add_argument("--exit-slippage-ticks", type=float, default=0.0)
backtest.add_argument("--execution-penalty", type=float, default=0.0)
paper_live.add_argument("--exit-slippage-ticks", type=float, default=0.0)
paper_live.add_argument("--execution-penalty", type=float, default=0.0)
```

```python
config = replace(
    TraderConfig.default(),
    paper=PaperExecutionConfig(
        exit_slippage_ticks=args.exit_slippage_ticks,
        execution_penalty_per_trade=args.execution_penalty,
    ),
)
```

- [ ] **Step 4: Re-run the focused tests to verify they pass**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_reporting -v`
Expected: `OK`

### Task 3: Run Focused Regression Checks

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_execution_realism.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`

- [ ] **Step 1: Run the direct regression slice**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_reporting tests.test_live_paper_runner tests.test_backtest -v`
Expected: `OK`

- [ ] **Step 2: Check lints/diagnostics on touched files**

Run diagnostics for:
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\backtest\engine.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_execution_realism.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`

- [ ] **Step 3: Summarize changed files and test results**

Report:
- the exact files changed
- the focused failing test signal
- the passing regression commands and outcomes

## Spec Coverage Check

- Integration tests for realism settings in artifacts: covered by Task 1
- Minimal threading through backtest/live/cli: covered by Task 2
- Focused regressions and result reporting: covered by Task 3

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task contains concrete files, commands, and assertions

## Type Consistency Check

- `PaperExecutionConfig` remains the realism config type throughout
- CLI flags use `exit_slippage_ticks` and `execution_penalty_per_trade` semantics consistently
- Artifact payload uses a top-level `paper` object in backtest JSON
