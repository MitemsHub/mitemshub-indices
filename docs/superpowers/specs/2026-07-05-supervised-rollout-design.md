# Supervised Rollout Design

## Summary

This design defines the first production-readiness rollout for the supervised trading system after the engineering phases for analytics, monitoring, latency visibility, venue handling, and final validation have been completed.

The rollout is based on the user's clarified real-world setup:

1. Deriv is the account and product ecosystem for the synthetic instruments.
2. MT5 is the connected execution platform used for trading Volatility 75 and Volatility 100.
3. The project's separation of `deriv` and `mt5` is a technical execution distinction, not a broker distinction.

Because of that, the recommended rollout treats MT5 as the primary live execution surface and treats direct Deriv execution as a secondary adapter that can be validated later.

The first rollout stage remains strictly `dry-run-live`. No real-money order placement is allowed until repeated sessions prove that readiness checks, symbol mapping, journaling, lifecycle handling, and operator review are all stable.

## Context

The repository already provides the operational foundations needed for a supervised rollout:

1. fail-closed readiness reporting for supervised live sessions,
2. explicit `paper`, `dry-run-live`, and `armed-live` execution modes,
3. MT5 runtime readiness evaluation,
4. MT5 lifecycle support for sync, reconcile, close, and modify actions,
5. MT5 analytics journaling and `mt5-monitor` operator review,
6. optional shared-path latency visibility,
7. final validation output for compact proof of system state.

These capabilities mean the next step is not more venue plumbing. The next step is a controlled operational rollout that uses the existing safeguards in the correct order.

## Goals

1. Define the safest first production-readiness path for the current MT5-connected Deriv setup.
2. Use the repo's existing supervised controls instead of inventing a parallel rollout process.
3. Keep the initial rollout fully operator-supervised and fail-closed.
4. Establish clear session rules, stop conditions, and scale criteria before any real-money execution.
5. Provide a practical checklist that can later be converted into an implementation or operator runbook plan.

## Non-Goals

1. No new strategy logic.
2. No model retraining redesign.
3. No removal or weakening of existing readiness gates.
4. No immediate dual-surface production rollout across MT5 and direct Deriv execution.
5. No unsupervised autonomous live trading.

## Design Principles

1. Match the rollout to the user's actual trading route.
2. Prove controls in `dry-run-live` before permitting `armed-live`.
3. Scale only after repeated, boring, stable sessions.
4. Stop immediately on state ambiguity, readiness drift, or operator uncertainty.
5. Increase exposure one variable at a time.

## Recommended Approach

### Why MT5 First

The user is trading Deriv synthetic instruments through a connected MT5 environment. In that context, MT5 is the execution surface that matters most for first rollout. It also has the strongest operator control coverage in the project today because it already supports:

1. runtime readiness checks,
2. symbol mapping validation,
3. lifecycle synchronization and reconciliation,
4. supervised close and modify handling,
5. analytics journaling,
6. operator-friendly monitor output.

Starting with MT5 keeps the rollout aligned with the real target environment and avoids diluting early live validation effort across two adapters at once.

### Why Dry-Run First

The first stage should remain fully `dry-run-live` even when readiness passes. This lets the system consume live conditions and traverse the supervised routing path without placing real orders.

That is the correct first gate because it proves:

1. readiness behavior under live conditions,
2. venue symbol resolution,
3. journal completeness,
4. monitor usefulness,
5. operator session discipline.

It also gives a stable baseline before any real-money risk is introduced.

## Rollout Stages

### Stage 1. Validation Replay

Before any live-style session, the operator should confirm that the latest validation and regression proof is current and representative.

Required outcomes:

1. the latest validation output exists,
2. the model version is known,
3. the symbol set is explicitly limited to Volatility 75 and Volatility 100,
4. the selected MT5 symbol mapping is confirmed,
5. the operator understands the current stop conditions and risk assumptions.

This stage is still preparation, not live rollout.

### Stage 2. MT5 Dry-Run Shadow Sessions

This is the first true rollout stage and the required starting point.

Session characteristics:

1. execution mode is `dry-run-live`,
2. venue is MT5,
3. one symbol is tested at a time,
4. session duration is limited,
5. operator remains present for the entire session,
6. all analytics and monitor outputs are preserved.

Stage 2 is considered successful only if repeated sessions remain operationally clean.

Pass conditions:

1. readiness stays green for the session,
2. no runtime or symbol mapping confusion occurs,
3. journal events are complete and readable,
4. `mt5-monitor` remains consistent with the expected session state,
5. no lifecycle ambiguity appears,
6. no manual rescue action is needed.

### Stage 3. Rule Lock And Operator Checklist

Before the first real-money session, the rollout must freeze explicit operator rules rather than relying on informal judgment.

The checklist should lock:

1. session start and stop rules,
2. maximum session duration,
3. maximum trades allowed per session,
4. maximum simultaneous positions,
5. daily stop conditions,
6. escalation behavior when the platform state is unclear.

This stage is a gate between shadow proof and real capital.

### Stage 4. Tiny Armed-Live Pilot

This stage begins only after Stage 2 has passed repeatedly and Stage 3 rules are frozen.

Pilot characteristics:

1. execution mode is `armed-live`,
2. size remains at the minimum practical live size,
3. only one symbol is active for the first sessions,
4. only one open position is allowed,
5. the operator is present for entry, management, and shutdown,
6. stop conditions are enforced aggressively.

The purpose of this stage is not profit maximization. The purpose is to prove clean order placement, lifecycle handling, and shutdown behavior with real money at the lowest practical risk.

### Stage 5. Controlled Scaling

Scaling begins only after several tiny live sessions complete cleanly.

Scaling must change one dimension at a time:

1. increase allowed session count, or
2. increase allowed trades per session, or
3. increase size slightly.

Do not increase multiple dimensions together. If problems appear, the rollout falls back to the last stable level.

### Stage 6. Secondary Adapter Review

Only after MT5 rollout is stable should the project decide whether direct Deriv execution deserves its own supervised rollout path.

This review should ask:

1. Is direct Deriv execution needed for production, or is MT5 sufficient?
2. Does direct Deriv execution offer a real operational advantage?
3. Would supporting both surfaces increase operator burden or failure modes?

This keeps the project focused on the user's actual route first.

## Session Rules

The rollout should use conservative session rules by default.

Recommended starting rules:

1. One symbol per session.
2. One open position maximum.
3. One operator present throughout the session.
4. Fixed session duration with a hard stop.
5. No continuation of a session after a stop condition is hit.
6. No same-session escalation from unstable dry-run behavior into armed-live behavior.

These rules are intentionally restrictive. Early rollout success should look quiet and controlled.

## Risk Caps

The initial production-readiness rollout should enforce stricter operational caps than the model might theoretically tolerate.

Recommended starting caps:

1. minimum practical live size only,
2. single-position limit,
3. hard daily loss stop,
4. hard consecutive-loss stop,
5. hard cap on trades per session,
6. mandatory shutdown on unresolved position state.

The goal is to protect the account while validating execution integrity, not to optimize return during rollout.

## Stop Conditions

The rollout must stop immediately when any of the following occur:

1. readiness flips from healthy to unhealthy,
2. MT5 runtime checks fail,
3. symbol mapping becomes unclear,
4. synchronization or reconciliation produces ambiguous state,
5. an unresolved position remains after expected lifecycle handling,
6. journal or monitor output becomes inconsistent with observed behavior,
7. the operator cannot explain the system state confidently,
8. the daily loss or consecutive-loss limit is hit.

A safe rollout is one that stops early when confidence is lost.

## Scale Criteria

The rollout may scale only after repeated sessions meet all of the following:

1. no readiness failures,
2. no unresolved positions,
3. no manual rescue workflows,
4. stable journal and monitor output,
5. stable operator interpretation of the session state,
6. acceptable latency visibility when profiling is enabled,
7. no breach of risk caps.

Scale decisions should be based on operational cleanliness first and PnL second.

## Operator Flow

The intended operator flow is:

1. confirm validation status,
2. confirm symbol and MT5 mapping,
3. start supervised MT5 dry-run session,
4. review journal and `mt5-monitor` outputs,
5. record whether the session passed or failed,
6. repeat until dry-run behavior is consistently stable,
7. authorize a tiny `armed-live` pilot only after the dry-run gate has clearly passed.

This creates a disciplined bridge between engineering completion and production exposure.

## Error Handling

The rollout design assumes fail-closed behavior throughout.

Operationally, that means:

1. readiness failures block progression,
2. unclear MT5 state blocks progression,
3. ambiguous lifecycle results block progression,
4. operator uncertainty blocks progression,
5. scaling pauses immediately after any abnormal session.

No part of the rollout should depend on "probably fine" reasoning.

## Testing And Evidence

The rollout itself is an operational process, but it should rely on existing repo evidence:

1. regression tests for the supervised live path,
2. regression tests for MT5 lifecycle handling,
3. regression tests for latency capture,
4. regression tests for validation output,
5. MT5 analytics journal records,
6. `mt5-monitor` session review output.

This keeps rollout decisions connected to evidence rather than intuition alone.

## Success Criteria

This supervised rollout design is successful when:

1. the first live rollout is explicitly aligned to the user's MT5-connected Deriv setup,
2. the first live stage is clearly defined as MT5 `dry-run-live`,
3. session rules, risk caps, stop conditions, and scale criteria are explicit,
4. `armed-live` is gated behind repeated clean shadow sessions,
5. the project remains fully supervised and fail-closed during rollout.

## Follow-On Plan

After this design is approved, the next planning step should convert it into a practical execution checklist and, where useful, small repo-facing improvements such as:

1. a rollout checklist document,
2. an operator runbook,
3. a compact session pass or fail record format,
4. any minimal CLI or reporting additions that materially improve supervised rollout discipline.
