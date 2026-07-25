# Changelog

All notable changes to Synthetic AI Trader are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.1.0] - 2026-07-25

### Added

#### Infrastructure & Deployment
- **Terraform templates** for AWS EC2 deployment (Windows Server 2022)
- Application Load Balancer with HTTP listener
- Security groups: RDP restricted to admin IP, web traffic through ALB
- Auto-start on boot via PM2 + Windows Scheduled Task
- Chocolatey-based provisioning: Node.js 20, Python 3.10, Git, PM2

#### Operator Dashboard (Next.js 15)
- **Trade Plan Panel** — Real-time trade recommendations with entry/invalidation/target levels
- **AI Market Intelligence** — Regime analysis, bias scoring, market thesis
- **Multi-Timeframe Alignment** — Visual alignment matrix across 4H→1H→15M→5M
- **Bullish vs Bearish Evidence** — Ranked evidence with strength bars
- **Current Market Thesis** — AI-generated thesis with confidence and invalidation
- **Health Dashboard** — System health monitoring, MT5 diagnostics, bridge status
- **Trade History** — Complete trade journal with outcomes and performance metrics
- **Mobile-First Design** — Responsive layout with bottom navigation
- **Dark Mode** — Full dark theme support with proper contrast ratios
- **Haptic Feedback** — Tactile feedback for mobile interactions (`src/components/ui/haptic.ts`)
- **Pull-to-Refresh** — Swipe down to refresh market data on mobile
- **Loading Skeletons** — Shimmer states for MultiTimeframe, Evidence, and MarketThesis panels
- **Intel Accordion** — Collapsible intelligence panels with smooth animations

#### Python Trading Engine
- **Missing live-watch functions restored** — `run_live_watch`, `render_live_snapshot_text`, `render_live_watch_alert_text`, `build_live_watch_review_snapshot`, `render_live_watch_review_text`, `build_watch_alert_from_prepared_state`, `_append_journal`
- **Bucket-based cooldown** — `DEFAULT_CONTEXT_ALERT_COOLDOWN=2` for context update suppression
- **StopIteration handling** — Clean exit when snapshot source is exhausted
- **MT5 price sanity check** — Alerts when CSV tick prices deviate from expected ranges
- **build_watch_alert** — Added `why` field from briefing for better explainability

#### Documentation
- **Comprehensive README.md** — Architecture diagrams, quickstart guide, CLI commands, deployment docs
- **CHANGELOG.md** — This file
- **Architecture diagrams** — ASCII art showing full system flow

### Fixed
- **Missing Python functions** that caused import errors breaking the Python engine bridge
- **Cooldown mechanism** — Restored bucket-based countdown (was incorrectly using 120-second epoch-based)
- **Dark mode command-rail** — Fixed washed-out appearance with proper dark theme CSS overrides
- **StopIteration in run_live_watch** — Previously fell into reconnect handler, creating spurious journal entries
- **build_decision_summary** — Now falls back to `briefing` when `why` is not present

### Changed
- **Merged feature/mt5-rollout-enablement into main** — All development consolidated into production branch
- **Updated .env.example** — `SYNTHETIC_ENGINE_MAX_LIVE_TICKS=5` → `15`
- **README overhaul** — Complete rewrite with architecture, features, CLI, and deployment documentation

---

## Previous Phases

### Phase 4 — AI Evolution & Self-Improving Intelligence
See [docs/PHASE4_SUMMARY.md](docs/PHASE4_SUMMARY.md)
- FeatureSelector, ModelCalibrator, ConfidenceScorer
- EnsembleModel, ModelMonitor, FeatureImportanceReport
- 13 new tests, experiment tracking framework

### Phase 3 — Core Intelligence Engine
See [docs/PHASE3_SUMMARY.md](docs/PHASE3_SUMMARY.md)
- 4-timeframe hierarchy with confluence scoring
- Continuous background scanner
- Call lifecycle management (forming→actionable→confirmed→failing→cancelled)
- Hurst exponent, entropy, volatility clustering
- FVG detection, internal BOS, equal highs/lows, liquidity sweeps
- Regime detection with persistence
- 8-component decision fusion
- Confidence calibration (isotonic + Platt)
- Explainability engine

### Phase 1–2 — Foundation
- Market data ingestion and candle construction
- Online logistic regression model
- Paper execution and journaling
- Walk-forward validation
- Risk engine with position sizing and drawdown limits
