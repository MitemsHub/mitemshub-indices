//+------------------------------------------------------------------+
//|                                       Tests/Phase6Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 unit tests.                |
//|                                                                  |
//|  Covers: PositionSizer (Python-parity stake + MT5 lot math),     |
//|  RiskLimits (Max* table, streaks, daily/hourly state, hard-limit |
//|  breach), DrawdownProtection (equity/daily drawdown halts),      |
//|  ExposureManager (hedging vs netting position rules), and the    |
//|  RiskEngine final-authority path (veto -> size).                 |
//|                                                                  |
//|  Mirrors mql5/phase6_logic_check.py assertion-for-assertion,     |
//|  which additionally checks the mirror against the REAL Python    |
//|  RiskEngine (stake formula, every veto gate's reason, the -0.10R |
//|  streak threshold, daily_drawdown_fraction) — so the compiled    |
//|  engine carries the research-lab risk semantics transitively.    |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 6 unit tests — Risk"

#include "../Core/Constants.mqh"
#include "../Risk/PositionSizer.mqh"
#include "../Risk/RiskLimits.mqh"
#include "../Risk/DrawdownProtection.mqh"
#include "../Risk/ExposureManager.mqh"
#include "../Risk/RiskEngine.mqh"

int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE6] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE6] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

StrategyCandidate MakeCand(const double conf, const double entry,
                           const double stop, const double target,
                           const int decision)
  {
   StrategyCandidate c;
   c.strategy = STRATEGY_BAND;
   c.decision = (ENUM_DECISION)decision;
   c.entry = entry;
   c.stop_loss = stop;
   c.take_profit = target;
   c.setup_quality = conf;
   c.confidence = conf;
   c.required_regime = REGIME_EXPANSION;
   c.reason_codes = "test";
   c.signal_strength = SIGNAL_STRONG_BUY;   // happy path: a STRONG verdict
   return(c);
  }

void TestPositionSizer()
  {
   Print("[PHASE6] --- PositionSizer ---");
   // stake: equity 10000, risk 0.5%, conf 0.90, min 0.48, scale 1.0
   double exp1 = MathMax(0.35, 50.0 * (0.55 + 0.70 * (0.90 - 0.48) / 0.52));
   double s1 = CPositionSizer::Stake(10000.0, 0.005, 0.90, 0.48, 1.0, 0.35);
   Check("stake conf=0.90 -> 55.77", CloseEnough(s1, exp1), StringFormat("%.4f", s1));
   Check("stake never exceeds 1.25x budget", s1 <= 50.0 * 1.25 + 1e-9);
   double s_floor = CPositionSizer::Stake(100.0, 0.005, 0.48, 0.48, 1.0, 0.35);
   Check("stake floor 0.35 applies at min confidence",
         CloseEnough(s_floor, 0.35), StringFormat("%.4f", s_floor));
   double s_half = CPositionSizer::Stake(10000.0, 0.005, 0.90, 0.48, 0.5, 0.35);
   Check("scale 0.5 halves stake", CloseEnough(s_half, exp1 * 0.5));
   Check("scale 0 -> paper-only 0",
         CPositionSizer::Stake(10000.0, 0.005, 0.90, 0.48, 0.0, 0.35) == 0.0);

   // lots: stake 55.77, dist 0.5, tick_value 0.1, tick_size 0.01 -> $5/lot -> 11.15
   double l1 = CPositionSizer::Lots(55.77, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01);
   Check("lots 55.77 stake -> 11.15", CloseEnough(l1, 11.15), StringFormat("%.4f", l1));
   double l_clamp = CPositionSizer::Lots(5000.0, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01);
   Check("lots clamps to vol_max 50", CloseEnough(l_clamp, 50.0));
   double l_floor = CPositionSizer::Lots(2.27, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01);
   Check("lots floors to step (2.27/5=0.454 -> 0.45)", CloseEnough(l_floor, 0.45));
   double l_degen = CPositionSizer::Lots(5.0, 100.0, 100.0, 0.1, 0.01, 0.01, 50.0, 0.01);
   Check("lots degenerate stop uses entry*0.001", l_degen > 0.0);
  }

void TestRiskLimits()
  {
   Print("[PHASE6] --- RiskLimits ---");
   CRiskLimits lm;
   lm.SetEquity(1000.0, 0);
   lm.SetEquity(1100.0, 0);
   lm.SetEquity(900.0, 0);
   Check("equity dd fraction 18.2%",
         CloseEnough(lm.EquityDrawdownFraction(), 200.0 / 1100.0));
   Check("equity dd 18.2% >= 15% breaches", lm.AnyHardLimitBreached());

   CRiskLimits lm2;
   lm2.SetEquity(1000.0, 0);
   lm2.RegisterOpen();               // open=1, trades_today=1
   Check("open>=max (1>=1) breaches", lm2.AnyHardLimitBreached());

   CRiskLimits lm3;
   lm3.SetMaxConsecutiveLosses(2);
   lm3.SetEquity(1000.0, 0);
   lm3.RegisterOutcome(-10.0, -0.5);   // material loss
   lm3.RegisterOutcome(-10.0, -0.5);   // streak 2
   Check("consecutive 2>=2 breaches", lm3.AnyHardLimitBreached());

   CRiskLimits lm4;
   lm4.SetEquity(1000.0, 0);
   lm4.SyncWindow(0, 1);            // day rollover: day_start = 1000
   lm4.SetEquity(940.0, 86400);     // same day, equity 940 -> 6% daily loss
   Check("daily loss 6% >= 5% breaches", lm4.AnyHardLimitBreached());
   lm4.SyncWindow(1, 1);            // hour rollover
   Check("hour rollover keeps day state",
         lm4.TradesToday() == 0 && CloseEnough(lm4.DayStartEquity(), 1000.0));

   CRiskLimits lm5;
   lm5.SetEquity(1000.0, 0);
   lm5.EmergencyStop(true);
   Check("EMERGENCY_STOP breaches everything", lm5.AnyHardLimitBreached());

   // streak threshold (Python parity)
   CRiskLimits lm6;
   lm6.SetEquity(1000.0, 0);
   lm6.RegisterOpen();
   lm6.RegisterOutcome(-0.01, -0.05);   // scratch -> streak stays 0
   Check("scratch -0.05R does NOT extend streak", lm6.ConsecutiveLosses() == 0);
   lm6.RegisterOpen();
   lm6.RegisterOutcome(-1.0, -0.15);    // material loss -> streak 1
   Check("material -0.15R loss extends streak", lm6.ConsecutiveLosses() == 1);
   lm6.RegisterOpen();
   lm6.RegisterOutcome(2.0, 0.5);       // win resets streak
   Check("win resets streak", lm6.ConsecutiveLosses() == 0);
  }

void TestDrawdownProtection()
  {
   Print("[PHASE6] --- DrawdownProtection ---");
   // Note: the day window (day_start / day_peak) is initialized by
   // OnNewSessionDay() — the RiskEngine calls it on first sync / day roll;
   // direct users must call it too (the mirror passes explicit day values).
   CDrawdownProtection dd;
   dd.SetLimits(0.10, 0.05, 0.02);
   dd.OnNewSessionDay();       // day starts at 0
   dd.SetEquity(1040.0);       // day peak 1040
   dd.SetEquity(985.0);        // loss 1.5%, peak-dd 5.3%
   Check("daily drawdown from peak halt",
         dd.Halted() == "daily_drawdown_limit");
   // isolate equity drawdown: loss 1.5%, equity-dd 10.5%
   CDrawdownProtection dd2;
   dd2.SetLimits(0.10, 0.05, 0.02);
   dd2.SetEquity(1100.0);      // all-time peak (previous day)
   dd2.SetEquity(1000.0);
   dd2.OnNewSessionDay();      // new day starts at 1000 (day_peak 1000)
   dd2.SetEquity(985.0);       // equity dd 115/1100 = 10.5%, day loss 1.5%
   Check("equity drawdown halt", dd2.Halted() == "equity_drawdown_limit");
   // daily loss first: 5% loss
   CDrawdownProtection dd3;
   dd3.SetLimits(0.10, 0.05, 0.02);
   dd3.SetEquity(1000.0);
   dd3.OnNewSessionDay();
   dd3.SetEquity(950.0);
   Check("daily loss limit halt", dd3.Halted() == "daily_loss_limit");
   // healthy
   CDrawdownProtection dd4;
   dd4.SetLimits(0.10, 0.05, 0.02);
   dd4.SetEquity(1000.0);
   dd4.OnNewSessionDay();
   dd4.SetEquity(995.0);
   Check("healthy -> no halt", dd4.Halted() == "");
  }

void TestExposureManager()
  {
   Print("[PHASE6] --- ExposureManager ---");
   // netting mode: one position total, either direction (plan gate)
   CExposureManager ex;
   ex.SetMode((int)ACCOUNT_MARGIN_MODE_RETAIL_NETTING);
   ex.SetLimits(1, 0.5);
   Check("netting: first position ok", ex.CanOpen(1));
   ex.RegisterOpen(1);
   Check("netting: second position (any dir) forbidden", !ex.CanOpen(-1));
   ex.RegisterClose(1);
   Check("netting: after close, re-open ok", ex.CanOpen(1));

   // hedging mode: one position per direction
   CExposureManager h;
   h.SetMode((int)ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
   h.SetLimits(2, 0.5);
   Check("hedging: long ok", h.CanOpen(1));
   h.RegisterOpen(1);
   Check("hedging: second long forbidden", !h.CanOpen(1));
   Check("hedging: opposite short allowed", h.CanOpen(-1));
   h.RegisterOpen(-1);
   Check("hedging: max open reached", !h.CanOpen(1));
   h.SetAccountState(1000.0, 600.0, 0.0);
   Check("exposure fraction 60%", CloseEnough(h.ExposureFraction(), 0.6));
   Check("exposure 60% >= 50% limit", h.ExposureExceedsLimit());
  }

void TestRiskEngine()
  {
   Print("[PHASE6] --- RiskEngine (final authority) ---");
   CRiskEngine re;
   re.SyncState(10000.0, 0.0, 0.0, 0);        // equity 10000, day 0/hour 0
   StrategyCandidate c = MakeCand(0.90, 100.0, 99.5, 102.0, DECISION_BUY);
   RiskVerdict v = re.Evaluate(c, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("approved with lots", v.approved && v.lots > 0.0,
         StringFormat("lots=%.4f stake=%.2f", v.lots, v.stake));
   Check("approved reasons mention risk approved",
         StringFind(v.reasons, "risk approved") >= 0);
   Check("stake matches sizer", CloseEnough(v.stake,
         CPositionSizer::Stake(10000.0, 0.005, 0.90, 0.48, 1.0, 0.35)));

   // paper-only scale -> approved but zero lots
   RiskVerdict vp = re.Evaluate(c, 0.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("paper-only approved, zero lots", vp.approved && vp.lots == 0.0);

   // EMERGENCY_STOP blocks everything
   re.EmergencyStop(true);
   RiskVerdict ve = re.Evaluate(c, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("EMERGENCY_STOP vetoes", !ve.approved
         && StringFind(ve.reasons, "EMERGENCY_STOP") >= 0);
   re.EmergencyStop(false);

   // confidence below min veto
   StrategyCandidate cw = MakeCand(0.40, 100.0, 99.5, 102.0, DECISION_BUY);
   RiskVerdict vw = re.Evaluate(cw, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("confidence below min vetoes", !vw.approved
         && StringFind(vw.reasons, "confidence") >= 0);

   // reward/risk below min veto (rr = 2/0.5 = 4.0 here, so make stop tight)
   StrategyCandidate cl = MakeCand(0.90, 100.0, 99.0, 100.5, DECISION_BUY); // rr 0.5
   RiskVerdict vl = re.Evaluate(cl, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("reward/risk below min vetoes", !vl.approved
         && StringFind(vl.reasons, "reward/risk") >= 0);

   // exposure veto: occupy the netting slot
   re.RegisterOpen(1);
   RiskVerdict vx = re.Evaluate(c, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("netting second position vetoes", !vx.approved
         && StringFind(vx.reasons, "max open positions") >= 0);
   re.RegisterClose(1);

   // Phase-5 decision-layer vetoes: WEAK verdict blocked before the sizer
   CRiskEngine re2;
   re2.SyncState(10000.0, 0.0, 0.0, 0);
   StrategyCandidate cweak = MakeCand(0.90, 100.0, 99.5, 102.0, DECISION_BUY);
   cweak.signal_strength = SIGNAL_WEAK_BUY;   // composite/confidence lands WEAK
   RiskVerdict vwk = re2.Evaluate(cweak, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("WEAK verdict vetoed before sizer", !vwk.approved && vwk.lots == 0.0
         && StringFind(vwk.reasons, "WEAK verdict") >= 0,
         StringFormat("reasons=%s", vwk.reasons));

   // WAIT verdict must never be sized (would otherwise slip past confidence)
   StrategyCandidate cwait = MakeCand(0.90, 100.0, 99.5, 102.0, DECISION_WAIT);
   cwait.signal_strength = SIGNAL_WAIT;
   RiskVerdict vwt = re2.Evaluate(cwait, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("WAIT verdict never sized", !vwt.approved && vwt.lots == 0.0
         && StringFind(vwt.reasons, "WAIT verdict") >= 0,
         StringFormat("reasons=%s", vwt.reasons));

   // STRONG verdict still approved when the gate is enabled
   StrategyCandidate cstrong = MakeCand(0.90, 100.0, 99.5, 102.0, DECISION_BUY);
   cstrong.signal_strength = SIGNAL_STRONG_BUY;
   RiskVerdict vst = re2.Evaluate(cstrong, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("STRONG verdict approved with gate on", vst.approved && vst.lots > 0.0,
         StringFormat("lots=%.4f", vst.lots));

   // gate off (research): WEAK verdict passes through to the sizing path
   re2.SetVetoWeakSignals(false);
   RiskVerdict vwk2 = re2.Evaluate(cweak, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("WEAK verdict passes when veto gate off", vwk2.approved && vwk2.lots > 0.0,
         StringFormat("approved=%d reasons=%s", vwk2.approved, vwk2.reasons));
   // WAIT veto is independent of the weak gate (never sized, ever)
   RiskVerdict vwt2 = re2.Evaluate(cwait, 1.0, 0.01, 50.0, 0.01, 0.1, 0.01);
   Check("WAIT veto persists with weak gate off", !vwt2.approved
         && StringFind(vwt2.reasons, "WAIT verdict") >= 0);
  }

int OnInit()
  {
   TestPositionSizer();
   TestRiskLimits();
   TestDrawdownProtection();
   TestExposureManager();
   TestRiskEngine();
   Print(StringFormat("[PHASE6] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail == 0)
      Print("[PHASE6] SUITE PASSED - Phase 6 complete");
   else
      Print("[PHASE6] SUITE FAILED - Phase 6 incomplete");
   return(INIT_SUCCEEDED);
  }

void OnTick() { }
