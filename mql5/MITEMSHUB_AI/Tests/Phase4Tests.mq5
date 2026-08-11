//+------------------------------------------------------------------+
//|                                       Tests/Phase4Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 4 unit tests.                |
//|                                                                  |
//|  Covers: BandGeometry (band_levels port, entry gates, breakeven  |
//|  trail) and the StrategyEngine regime-allowance matrix.          |
//|                                                                  |
//|  The hardcoded level expectations are the values produced by the |
//|  REAL Python band_geometry.py (band_levels) on the shared cases  |
//|  — the Phase-4 gate is \"band leg reproduces Python band_levels   |
//|  within tolerance\".  Mirrors mql5/phase4_logic_check.py          |
//|  assertion-for-assertion (which additionally checks the mirror   |
//|  against the real Python module to 1e-12).                       |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 4 unit tests — Strategies"

#include "../Core/Constants.mqh"
#include "../Strategies/BandGeometry.mqh"
#include "../Strategies/TrendContinuation.mqh"
#include "../Strategies/BreakoutStrategy.mqh"
#include "../Strategies/MeanReversion.mqh"
#include "../Strategies/LiquiditySweep.mqh"
#include "../Strategies/PullbackStrategy.mqh"
#include "../Strategies/StrategyEngine.mqh"

int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE4] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE4] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

void TestBandLevels()
  {
   Print("[PHASE4] --- band_levels (Python values, tol 1e-9) ---");
   CBandGeometry::BandLevels lv;
   // A: buy 100, sigma 0.005, 300s bars, 1h hold, defaults (0.20/0.80)
   bool okA = CBandGeometry::ComputeLevels(100.0, 1, 0.005, 300, 3600,
                                           0.20, 0.80, 2.0, 0.015, lv);
   Check("A buy geometry ok", okA);
   Check("A stop 99.653589838486", okA && CloseEnough(lv.stop_loss, 99.653589838486, 1e-9),
         StringFormat("%.12f", lv.stop_loss));
   Check("A tp 101.385640646055", okA && CloseEnough(lv.take_profit, 101.385640646055, 1e-9),
         StringFormat("%.12f", lv.take_profit));
   Check("A rr 4.0", okA && CloseEnough(lv.reward_risk, 4.0, 1e-9));
   Check("A sigma_h 0.017320508076", okA && CloseEnough(lv.horizon_sigma, 0.017320508076, 1e-9));
   Check("A hold 3600", okA && lv.hold_sec == 3600);

   // B: sell, same inputs — stop above, target below
   CBandGeometry::BandLevels lvB;
   bool okB = CBandGeometry::ComputeLevels(100.0, -1, 0.005, 300, 3600,
                                           0.20, 0.80, 2.0, 0.015, lvB);
   Check("B sell stop above entry", okB && CloseEnough(lvB.stop_loss, 100.346410161514, 1e-9),
         StringFormat("%.12f", lvB.stop_loss));
   Check("B sell tp below entry", okB && CloseEnough(lvB.take_profit, 98.614359353945, 1e-9),
         StringFormat("%.12f", lvB.take_profit));

   // E: 2h hold scales sigma_h by sqrt(2)
   CBandGeometry::BandLevels lvE;
   bool okE = CBandGeometry::ComputeLevels(100.0, 1, 0.005, 300, 7200,
                                           0.20, 0.80, 2.0, 0.015, lvE);
   Check("E 2h stop 99.510102051443", okE && CloseEnough(lvE.stop_loss, 99.510102051443, 1e-9),
         StringFormat("%.12f", lvE.stop_loss));
   Check("E 2h tp 101.959591794227", okE && CloseEnough(lvE.take_profit, 101.959591794227, 1e-9),
         StringFormat("%.12f", lvE.take_profit));

   Print("[PHASE4] --- band_levels guards ---");
   Check("rr < min_rr -> false",
         !CBandGeometry::ComputeLevels(100.0, 1, 0.005, 300, 3600, 0.20, 0.30, 2.0, 0.015, lv));
   Check("stop > max_stop_pct -> false",
         !CBandGeometry::ComputeLevels(100.0, 1, 0.2, 300, 3600, 0.20, 0.80, 2.0, 0.015, lv));
   Check("entry <= 0 -> false",
         !CBandGeometry::ComputeLevels(0.0, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015, lv));
   Check("sigma <= 0 -> false",
         !CBandGeometry::ComputeLevels(100.0, 1, 0.0, 300, 3600, 0.20, 0.80, 2.0, 0.015, lv));
   Check("bad direction -> false",
         !CBandGeometry::ComputeLevels(100.0, 0, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015, lv));
   Check("hold <= 0 -> false",
         !CBandGeometry::ComputeLevels(100.0, 1, 0.005, 300, 0, 0.20, 0.80, 2.0, 0.015, lv));
  }

void TestEntryGates()
  {
   Print("[PHASE4] --- entry gates ---");
   Check("vol extended 0.14 > 1.3x0.1", CBandGeometry::VolExtended(0.14, 0.10, 1.3));
   Check("vol not extended 0.12 < 1.3x0.1", !CBandGeometry::VolExtended(0.12, 0.10, 1.3));
   Check("boundary 0.13 == 1.3x0.1 not >", !CBandGeometry::VolExtended(0.13, 0.10, 1.3));
   Check("z +1.5 -> sell", CBandGeometry::EntryDirection(1.5, 1.0) == -1);
   Check("z -1.5 -> buy", CBandGeometry::EntryDirection(-1.5, 1.0) == 1);
   Check("z +1.0 boundary -> sell", CBandGeometry::EntryDirection(1.0, 1.0) == -1);
   Check("z 0.5 -> none", CBandGeometry::EntryDirection(0.5, 1.0) == 0);
   Check("conf z=1 0.8833", CloseEnough(CBandGeometry::Confidence(1.0, 1.0), 0.883333333, 1e-6));
   Check("conf z=3 0.9", CloseEnough(CBandGeometry::Confidence(3.0, 1.0), 0.9, 1e-9));
   Check("conf z=10 clamped 0.9", CloseEnough(CBandGeometry::Confidence(10.0, 1.0), 0.9, 1e-9));
  }

void TestBreakevenTrail()
  {
   Print("[PHASE4] --- breakeven trail ---");
   Check("MFE buy 1.25",
         CloseEnough(CBandGeometry::UpdateMFE(1, 100.0, 100.5, 99.2, 0.0, 0.4), 1.25, 1e-9));
   Check("MFE sell 2.0",
         CloseEnough(CBandGeometry::UpdateMFE(-1, 100.0, 100.5, 99.2, 0.0, 0.4), 2.0, 1e-9));
   Check("MFE max tracks",
         CloseEnough(CBandGeometry::UpdateMFE(1, 100.0, 100.3, 99.5, 1.25, 0.4), 1.25, 1e-9));
   Check("trail not armed below frac", !CBandGeometry::TrailArmed(1.0, 0.3, 3.5));
   Check("trail armed at 0.3 x 3.5", CBandGeometry::TrailArmed(1.05, 0.3, 3.5));
   Check("trail disabled frac=0", !CBandGeometry::TrailArmed(2.0, 0.0, 3.5));
   Check("effective stop = entry when armed",
         CloseEnough(CBandGeometry::EffectiveStop(true, 100.0, 99.6), 100.0));
   Check("effective stop = stop when not armed",
         CloseEnough(CBandGeometry::EffectiveStop(false, 100.0, 99.6), 99.6));
  }

void TestStrategyEngine()
  {
   Print("[PHASE4] --- StrategyEngine matrix ---");
   // Disabled state: only the validated band leg is allowed anywhere.
   ENUM_REGIME regs[] = {REGIME_TREND_UP, REGIME_RANGE, REGIME_COMPRESSION, REGIME_EXPANSION};
   for(int i = 0; i < ArraySize(regs); i++)
     {
      Check("disabled: band allowed in regime " + RegimeToString(regs[i]),
            CStrategyEngine::IsAllowed(STRATEGY_BAND, regs[i]));
      Check("disabled: trend blocked in regime " + RegimeToString(regs[i]),
            !CStrategyEngine::IsAllowed(STRATEGY_TREND, regs[i]));
      Check("disabled: meanrev blocked in regime " + RegimeToString(regs[i]),
            !CStrategyEngine::IsAllowed(STRATEGY_MEANREVERSION, regs[i]));
     }

   // Target end-state matrix (research strategies OFF until validated OOS).
   Check("TREND_UP allows trend", CStrategyEngine::MatrixAllows(STRATEGY_TREND, REGIME_TREND_UP));
   Check("TREND_UP blocks meanrev", !CStrategyEngine::MatrixAllows(STRATEGY_MEANREVERSION, REGIME_TREND_UP));
   Check("TREND_DOWN allows pullback", CStrategyEngine::MatrixAllows(STRATEGY_PULLBACK, REGIME_TREND_DOWN));
   Check("RANGE allows meanrev", CStrategyEngine::MatrixAllows(STRATEGY_MEANREVERSION, REGIME_RANGE));
   Check("RANGE allows sweep", CStrategyEngine::MatrixAllows(STRATEGY_LIQUIDITY_SWEEP, REGIME_RANGE));
   Check("RANGE blocks trend", !CStrategyEngine::MatrixAllows(STRATEGY_TREND, REGIME_RANGE));
   Check("COMPRESSION allows breakout", CStrategyEngine::MatrixAllows(STRATEGY_BREAKOUT, REGIME_COMPRESSION));
   Check("COMPRESSION blocks pullback", !CStrategyEngine::MatrixAllows(STRATEGY_PULLBACK, REGIME_COMPRESSION));
   Check("EXPANSION band only",
         CStrategyEngine::MatrixAllows(STRATEGY_BAND, REGIME_EXPANSION) &&
         !CStrategyEngine::MatrixAllows(STRATEGY_BREAKOUT, REGIME_EXPANSION));

   // End-state matrix lists (mirror-consistent: the mirror builds its lists
   // from matrix_allows_m, the matrix without the research-disabled guard).
   ENUM_STRATEGY up_list[];
   ArrayResize(up_list, 0);
   for(int s = (int)STRATEGY_BAND; s <= (int)STRATEGY_PULLBACK; s++)
      if(CStrategyEngine::MatrixAllows((ENUM_STRATEGY)s, REGIME_TREND_UP))
        {
         int n = ArraySize(up_list);
         ArrayResize(up_list, n + 1);
         up_list[n] = (ENUM_STRATEGY)s;
        }
   bool up_ok = ArraySize(up_list) == 4 && up_list[0] == STRATEGY_BAND &&
                up_list[1] == STRATEGY_TREND && up_list[2] == STRATEGY_BREAKOUT &&
                up_list[3] == STRATEGY_PULLBACK;
   Check("TREND_UP allowed list", up_ok, StringFormat("n=%d", ArraySize(up_list)));
   ENUM_STRATEGY range_list[];
   ArrayResize(range_list, 0);
   for(int s = (int)STRATEGY_BAND; s <= (int)STRATEGY_PULLBACK; s++)
      if(CStrategyEngine::MatrixAllows((ENUM_STRATEGY)s, REGIME_RANGE))
        {
         int n = ArraySize(range_list);
         ArrayResize(range_list, n + 1);
         range_list[n] = (ENUM_STRATEGY)s;
        }
   bool range_ok = ArraySize(range_list) == 3 && range_list[0] == STRATEGY_BAND &&
                   range_list[1] == STRATEGY_MEANREVERSION && range_list[2] == STRATEGY_LIQUIDITY_SWEEP;
   Check("RANGE allowed list", range_ok, StringFormat("n=%d", ArraySize(range_list)));

   // Runtime behavior today: research hard-disabled -> only the band is live.
   ENUM_STRATEGY live[];
   int nlive = CStrategyEngine::AllowedStrategies(REGIME_TREND_UP, live, 8);
   Check("runtime allowed = band only (research disabled)",
         nlive == 1 && live[0] == STRATEGY_BAND, StringFormat("n=%d", nlive));

   Print("[PHASE4] --- band candidate dispatch ---");
   CStrategyEngine::BandContext ctx;
   ctx.entry = 100.0; ctx.direction = 1; ctx.sigma_per_bar = 0.005;
   ctx.bar_sec = 300; ctx.hold_sec = 3600;
   ctx.stop_sigma_mult = 0.20; ctx.target_sigma_mult = 0.80;
   ctx.min_target_rr = 2.0; ctx.max_stop_pct = 0.015;
   StrategyCandidate cand = CStrategyEngine::Evaluate(STRATEGY_BAND, ctx);
   Check("band candidate BUY", cand.decision == DECISION_BUY,
         StringFormat("dec=%d", cand.decision));
   Check("band candidate stop matches Python",
         CloseEnough(cand.stop_loss, 99.653589838486, 1e-9));
   Check("band candidate tp matches Python",
         CloseEnough(cand.take_profit, 101.385640646055, 1e-9));
   ctx.direction = -1;
   cand = CStrategyEngine::Evaluate(STRATEGY_BAND, ctx);
   Check("band candidate SELL", cand.decision == DECISION_SELL);
   Check("band sell stop above", CloseEnough(cand.stop_loss, 100.346410161514, 1e-9));
   ctx.direction = 0;
   cand = CStrategyEngine::Evaluate(STRATEGY_BAND, ctx);
   Check("band candidate WAIT on no direction", cand.decision == DECISION_WAIT);
   cand = CStrategyEngine::Evaluate(STRATEGY_TREND, ctx);
   Check("research stub returns WAIT", cand.decision == DECISION_WAIT &&
         StringFind(cand.reason_codes, "research") >= 0, cand.reason_codes);
  }

//+------------------------------------------------------------------+
//| OnInit — run the suite                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[PHASE4] === MITEMSHUB Phase 4 unit tests starting ===");
   TestBandLevels();
   TestEntryGates();
   TestBreakevenTrail();
   TestStrategyEngine();
   Print(StringFormat("[PHASE4] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail > 0)
     {
      Print("[PHASE4] SUITE FAILED — do not proceed to Phase 5");
      return(INIT_FAILED);
     }
   Print("[PHASE4] SUITE PASSED — Phase 4 complete");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
