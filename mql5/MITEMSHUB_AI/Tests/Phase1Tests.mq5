//+------------------------------------------------------------------+
//|                                       Tests/Phase1Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 1 unit tests.                |
//|                                                                  |
//|  Compile:   MetaEditor (F7).  Run: attach to any chart —         |
//|  OnInit runs the suite and writes PASS/FAIL lines to the log,    |
//|  then returns INIT_FAILED if any test failed (so a green init    |
//|  in the Experts log means all tests passed).                     |
//|                                                                  |
//|  Tests use known-good values — including the REAL Deriv      |
//|  SYN75/SYN100 specs probed live — so a regression is caught      |
//|  immediately.                                                    |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 1 unit tests — Core + Market"

#include "../Core/Constants.mqh"
#include "../Core/Config.mqh"
#include "../Core/StateManager.mqh"
#include "../Market/SymbolAdapter.mqh"
#include "../Market/NormalizationEngine.mqh"
#include "../Market/VolatilityEngine.mqh"

//--- test counters -----------------------------------------------------------
int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE1] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE1] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol)
  {
   return(MathAbs(a - b) <= tol);
  }

//+------------------------------------------------------------------+
//| Test groups                                                       |
//+------------------------------------------------------------------+
void TestConstants()
  {
   Print("[PHASE1] --- Constants ---");
   Check("RegimeToString TREND_UP", RegimeToString(REGIME_TREND_UP) == "TREND_UP");
   Check("RegimeToString UNKNOWN", RegimeToString(REGIME_UNKNOWN) == "UNKNOWN");
   Check("DecisionToString BUY", DecisionToString(DECISION_BUY) == "BUY");
   Check("DecisionToString WAIT", DecisionToString(DECISION_WAIT) == "WAIT");
   Check("StrategyToString BAND", StrategyToString(STRATEGY_BAND) == "BAND_GEOMETRY");
   Check("ExitReasonToString STOP_HIT", ExitReasonToString(EXIT_STOP_HIT) == "STOP_HIT");
   Check("live disabled by default", InpLiveTradingEnabled == false);
   Check("emergency stop default off", InpEmergencyStop == false);
   Check("band enabled by default", InpEnableBandGeometry == true);
   Check("research strategies OFF by default",
         InpEnableTrend == false && InpEnableBreakout == false &&
         InpEnableMeanReversion == false && InpEnableLiquiditySweep == false &&
         InpEnablePullback == false);
  }

void TestConfig()
  {
   Print("[PHASE1] --- Config ---");
   Check("cfgRiskPerTradePct matches input", cfgRiskPerTradePct() == InpRiskPerTradePct);
   Check("cfgMaxOpenPositions matches input", cfgMaxOpenPositions() == InpMaxOpenPositions);
   Check("cfgBandZEntry matches input", cfgBandZEntry() == InpBandZEntry);
   Check("cfgMinConfidence matches input", cfgMinConfidence() == InpMinConfidence);
   Check("cfgMagic matches input", cfgMagic() == InpMagic);
  }

void TestSymbolAdapterFixture()
  {
   Print("[PHASE1] --- SymbolAdapter (real Deriv fixtures) ---");
   CSymbolAdapter adapter;
   SymbolSpec spec;
   CSymbolAdapter::FillFixture("SYN75", spec);

   Check("SYN75 fixture valid", spec.valid);
   Check("SYN75 digits=3", spec.digits == 3);
   Check("SYN75 point=0.001", CloseEnough(spec.point, 0.001, 1e-9));
   Check("SYN75 tick_size=0.001", CloseEnough(spec.tick_size, 0.001, 1e-9));
   Check("SYN75 tick_value=0.1", CloseEnough(spec.tick_value, 0.1, 1e-9));
   Check("SYN75 contract=100", CloseEnough(spec.contract_size, 100.0, 1e-9));
   Check("SYN75 volume_min=0.01", CloseEnough(spec.volume_min, 0.01, 1e-9));
   Check("SYN75 volume_max=100", CloseEnough(spec.volume_max, 100.0, 1e-9));
   Check("SYN75 volume_step=0.01", CloseEnough(spec.volume_step, 0.01, 1e-9));
   Check("SYN75 stops_level=0", spec.stops_level == 0);
   Check("SYN75 spread ~1080 pts", CloseEnough(spec.spread_points, 1080.0, 5.0));

   // volume normalization on the fixture grid
   CSymbolAdapter n;
   // Use fixture values directly to test NormalizeVolume math:
   // min 0.01, max 100, step 0.01
   double v;
   v = n.NormalizeVolumeFromSpec(spec, 0.0);   Check("vol 0 -> min", CloseEnough(v, 0.01, 1e-9));
   v = n.NormalizeVolumeFromSpec(spec, 0.123); Check("vol 0.123 -> 0.12", CloseEnough(v, 0.12, 1e-9));
   v = n.NormalizeVolumeFromSpec(spec, 250.0); Check("vol 250 -> max", CloseEnough(v, 100.0, 1e-9));
   v = n.NormalizeVolumeFromSpec(spec, 0.25);  Check("vol 0.25 -> 0.25", CloseEnough(v, 0.25, 1e-9));
  }

void TestNormalization()
  {
   Print("[PHASE1] --- NormalizationEngine ---");
   CNormalizationEngine ne;
   Check("RangeToATR 2.0/1.0 = 2.0", CloseEnough(ne.RangeToATR(102.0, 100.0, 1.0), 2.0, 1e-9));
   Check("RangeToATR atr<=0 -> 0", CloseEnough(ne.RangeToATR(102.0, 100.0, 0.0), 0.0, 1e-9));
   Check("BodyToATR |101-100|/1 = 1", CloseEnough(ne.BodyToATR(100.0, 101.0, 1.0), 1.0, 1e-9));
   Check("LogReturn 100->110 ~ 0.0953", CloseEnough(ne.LogReturn(100.0, 110.0), 0.095310, 1e-4));
   Check("PctReturn 100->110 = 0.1", CloseEnough(ne.PctReturn(100.0, 110.0), 0.1, 1e-9));
   Check("ZScore (10,5,2.5) = 2", CloseEnough(ne.ZScore(10.0, 5.0, 2.5), 2.0, 1e-9));
   Check("ZScore std<=0 -> 0", CloseEnough(ne.ZScore(10.0, 5.0, 0.0), 0.0, 1e-9));
   Check("RelativeDistance (12,10,1) = 2", CloseEnough(ne.RelativeDistance(12.0, 10.0, 1.0), 2.0, 1e-9));
   Check("CloseLocation low=0", CloseEnough(ne.CloseLocation(10.0, 8.0, 8.0), 0.0, 1e-9));
   Check("CloseLocation high=1", CloseEnough(ne.CloseLocation(10.0, 8.0, 10.0), 1.0, 1e-9));

   // efficiency ratio: pure ramp = 1.0
   double closes[5];
   closes[0] = 100.0; closes[1] = 101.0; closes[2] = 102.0;
   closes[3] = 103.0; closes[4] = 104.0;
   Check("EfficiencyRatio ramp = 1", CloseEnough(ne.EfficiencyRatio(closes, 5), 1.0, 1e-9));
   // zig-zag: net 0 -> 0
   closes[0] = 100.0; closes[1] = 102.0; closes[2] = 100.0;
   closes[3] = 102.0; closes[4] = 100.0;
   Check("EfficiencyRatio zigzag = 0", CloseEnough(ne.EfficiencyRatio(closes, 5), 0.0, 1e-9));
  }

void TestVolatility()
  {
   Print("[PHASE1] --- VolatilityEngine ---");
   CVolatilityEngine ve;
   ve.SetPeriod(14);

   // Constant range 2.0 bars: ATR converges to 2.0.
   // Bars must track the drift (high=prev+1, low=prev-1) so the previous
   // close stays inside the candle — fixed high/low with a drifting close
   // would invert the candle and balloon the true range.
   double prev = 100.0;
   for(int i = 0; i < 100; i++)
     {
      double high = prev + 1.0;
      double low  = prev - 1.0;
      double close = prev + 0.5;   // mild drift
      ve.OnBarWithPrevClose(prev, high, low, close);
      prev = close;
     }
   Check("ATR converges to 2.0", CloseEnough(ve.ATR(), 2.0, 0.05));
   // Constant ATR series: strict-< rank means nothing is below the current
   // value, so the percentile is 0.0 (expansion test below covers the rise).
   Check("ATR percentile 0 for constant ATR", CloseEnough(ve.ATRPercentile(50), 0.0, 0.05));

   // Now a huge expansion bar: ATR percentile should jump high
   CVolatilityEngine ve2;
   ve2.SetPeriod(5);
   prev = 100.0;
   for(int i = 0; i < 40; i++)
     {
      ve2.OnBarWithPrevClose(prev, prev + 0.5, prev - 0.5, prev + 0.1);
      prev += 0.1;
     }
   // expansion bar: range 10x
   ve2.OnBarWithPrevClose(prev, prev + 5.0, prev - 5.0, prev + 2.0);
   Check("expansion bar detected", ve2.IsExpanding(30));
   Check("ATR percentile high after expansion", ve2.ATRPercentile(30) > 0.7);
   Check("RealizedVol positive", ve2.RealizedVol(10) > 0.0);
  }

void TestStateManager()
  {
   Print("[PHASE1] --- StateManager ---");
   CStateManager sm;
   Check("initial regime UNKNOWN", sm.Regime() == REGIME_UNKNOWN);
   Check("initial decision WAIT", sm.LastDecision() == DECISION_WAIT);
   Check("no open position initially", !sm.HasOpenPosition());
   Check("no hard halt initially", !sm.HardHalt());

   sm.SetRegime(REGIME_RANGE, 0.82);
   Check("regime set", sm.Regime() == REGIME_RANGE);
   Check("regime confidence set", CloseEnough(sm.RegimeConfidence(), 0.82, 1e-9));

   sm.SetDecision(DECISION_WAIT, "REGIME=RANGE SETUP=54 RR=INSUFFICIENT", 54.0, 0.31, 0.0, STRATEGY_BAND);
   Check("decision WAIT set", sm.LastDecision() == DECISION_WAIT);
   Check("reason preserved", sm.LastDecisionReason() == "REGIME=RANGE SETUP=54 RR=INSUFFICIENT");
   Check("score preserved", CloseEnough(sm.LastScore(), 54.0, 1e-9));

   sm.SetOpenPosition(12345);
   Check("open position set", sm.HasOpenPosition());
   Check("ticket preserved", sm.OpenPositionTicket() == 12345);

   sm.SetHardHalt(true);
   Check("hard halt set", sm.HardHalt());

   sm.SetDecision(DECISION_BUY, "aligned", 80.0, 0.75, 2.7, STRATEGY_BAND);
   Check("decision BUY set", sm.LastDecision() == DECISION_BUY);
   Check("expected RR preserved", CloseEnough(sm.LastExpectedRR(), 2.7, 1e-9));
  }

//+------------------------------------------------------------------+
//| OnInit — run the suite                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[PHASE1] === MITEMSHUB Phase 1 unit tests starting ===");
   TestConstants();
   TestConfig();
   TestSymbolAdapterFixture();
   TestNormalization();
   TestVolatility();
   TestStateManager();
   Print(StringFormat("[PHASE1] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail > 0)
     {
      Print("[PHASE1] SUITE FAILED — do not proceed to Phase 2");
      return(INIT_FAILED);
     }
   Print("[PHASE1] SUITE PASSED — Phase 1 complete");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
