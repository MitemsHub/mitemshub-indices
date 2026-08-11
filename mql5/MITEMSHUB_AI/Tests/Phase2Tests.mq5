//+------------------------------------------------------------------+
//|                                       Tests/Phase2Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 2 unit tests.                |
//|                                                                  |
//|  Covers: TimeframeManager, CandleEngine, TrendDetector,          |
//|  RangeDetector, CompressionDetector, ExpansionDetector,          |
//|  TransitionDetector, HurstAnalyzer, RegimeEngine.                |
//|                                                                  |
//|  Mirrors mql5/phase2_logic_check.py assertion-for-assertion.     |
//|  Run: attach to any chart; OnInit runs the suite and reports     |
//|  PASS/FAIL to the log (INIT_FAILED if any test fails).           |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 2 unit tests — Market infra + Regime"

#include "../Core/Constants.mqh"
#include "../Core/Config.mqh"
#include "../Core/StateManager.mqh"
#include "../Market/SymbolAdapter.mqh"
#include "../Market/NormalizationEngine.mqh"
#include "../Market/VolatilityEngine.mqh"
#include "../Market/TimeframeManager.mqh"
#include "../Market/CandleEngine.mqh"
#include "../Market/MarketData.mqh"
#include "../Regime/TrendDetector.mqh"
#include "../Regime/RangeDetector.mqh"
#include "../Regime/CompressionDetector.mqh"
#include "../Regime/ExpansionDetector.mqh"
#include "../Regime/TransitionDetector.mqh"
#include "../Regime/HurstAnalyzer.mqh"
#include "../Regime/RegimeEngine.mqh"

//--- test counters -----------------------------------------------------------
int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE2] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE2] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol)
  {
   return(MathAbs(a - b) <= tol);
  }

//--- deterministic gaussian (Box-Muller on MathRand; seed for repeatability) --
double g_next_gauss;
void RngSeed(const int seed)        { MathSrand(seed); }
double NextGaussian()
  {
   double u1 = (MathRand() + 1.0) / 32768.0;
   double u2 = (MathRand() + 1.0) / 32768.0;
   return(MathSqrt(-2.0 * MathLog(u1)) * MathCos(2.0 * M_PI * u2));
  }

//--- synthetic series builders ------------------------------------------------
// ramp: monotonic rise
void BuildRamp(double &out[], const int n, const double step = 0.5, const double start = 100.0)
  {
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
      out[i] = start + i * step;
  }

// zigzag: alternating around a fixed level
void BuildZigzag(double &out[], const int n, const double amp = 1.0, const double start = 100.0)
  {
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
      out[i] = (i % 2 == 0) ? start + amp : start - amp;
  }

// oscillation: sine around a fixed level
void BuildOscillation(double &out[], const int n, const double amp = 1.0, const int period = 8,
                      const double start = 100.0)
  {
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
      out[i] = start + amp * MathSin(2.0 * M_PI * i / period);
  }

// random walk
void BuildRandomWalk(double &out[], const int n, const int seed)
  {
   ArrayResize(out, n);
   RngSeed(seed);
   out[0] = 100.0;
   for(int i = 1; i < n; i++)
      out[i] = out[i - 1] + NextGaussian();
  }

// strongly persistent: drift dominates noise
void BuildPersistent(double &out[], const int n, const int seed)
  {
   ArrayResize(out, n);
   RngSeed(seed);
   out[0] = 100.0;
   for(int i = 1; i < n; i++)
      out[i] = out[i - 1] + 0.2 + 0.02 * NextGaussian();
  }

// mean-reverting: pull back toward a fixed mean
void BuildMeanReverting(double &out[], const int n, const int seed)
  {
   ArrayResize(out, n);
   RngSeed(seed);
   out[0] = 100.0;
   for(int i = 1; i < n; i++)
      out[i] = out[i - 1] + 0.6 * (100.0 - out[i - 1]) + 0.15 * NextGaussian();
  }

//+------------------------------------------------------------------+
//| Test groups                                                       |
//+------------------------------------------------------------------+
void TestTimeframeManager()
  {
   Print("[PHASE2] --- TimeframeManager ---");
   CTimeframeManager tfm;
   Check("defaults macro H4", tfm.Macro() == DEFAULT_TF_MACRO);
   Check("defaults execution M1", tfm.Execution() == DEFAULT_TF_EXECUTION);
   Check("M1=60s", CTimeframeManager::SecondsOf(PERIOD_M1) == 60);
   Check("H1=3600s", CTimeframeManager::SecondsOf(PERIOD_H1) == 3600);
   Check("H4=14400s", CTimeframeManager::SecondsOf(PERIOD_H4) == 14400);
   Check("D1=86400s", CTimeframeManager::SecondsOf(PERIOD_D1) == 86400);
   Check("MN1=2592000s", CTimeframeManager::SecondsOf(PERIOD_MN1) == 2592000L);

   CTimeframeManager tfm2;
   Check("valid stack accepted", tfm2.SetTimeframes(PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5, PERIOD_M1));
   Check("valid stack valid flag", tfm2.Valid());
   CTimeframeManager tfm3;
   Check("inverted order rejected",
         !tfm3.SetTimeframes(PERIOD_M1, PERIOD_H4, PERIOD_M15, PERIOD_M5, PERIOD_M1));
   Check("inverted order invalid flag", !tfm3.Valid());
   CTimeframeManager tfm4;
   Check("unknown tf rejected", !tfm4.SetTimeframes((ENUM_TIMEFRAMES)99, PERIOD_H1,
                                                    PERIOD_M15, PERIOD_M5, PERIOD_M1));
  }

void TestCandleEngine()
  {
   Print("[PHASE2] --- CandleEngine ---");
   CCandleEngine ce;
   ce.RegisterTimeframe(PERIOD_M5);
   for(int i = 0; i < 10; i++)
      ce.PushBar(PERIOD_M5, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, (datetime)(1000 + i));
   Check("count=10", ce.Count(PERIOD_M5) == 10);
   double c;
   Check("newest = last pushed", ce.GetClose(PERIOD_M5, 0, c) && CloseEnough(c, 109.5, 1e-9));
   Check("shift1 = second newest", ce.GetClose(PERIOD_M5, 1, c) && CloseEnough(c, 108.5, 1e-9));
   double closes[];
   Check("closes oldest-first available", ce.GetCloses(PERIOD_M5, closes, 5));
   bool oldest_first = CloseEnough(closes[0], 105.5, 1e-9) && CloseEnough(closes[4], 109.5, 1e-9);
   Check("closes oldest-first order", oldest_first);
   Check("unregistered tf count 0", ce.Count(PERIOD_H1) == 0);
   Check("unregistered tf GetBar false", !ce.GetClose(PERIOD_H1, 0, c));

   CCandleEngine ce2;
   ce2.RegisterTimeframe(PERIOD_M5);
   for(int i = 0; i < 600; i++)
      ce2.PushBar(PERIOD_M5, 0.0, 0.0, 0.0, (double)i, (datetime)i);
   Check("ring wraps at 500", ce2.Count(PERIOD_M5) == 500);
   Check("ring newest preserved", ce2.GetClose(PERIOD_M5, 0, c) && CloseEnough(c, 599.0, 1e-9));
   Check("ring oldest evicted", ce2.GetClose(PERIOD_M5, 499, c) && CloseEnough(c, 100.0, 1e-9));
  }

void TestTrendDetector()
  {
   Print("[PHASE2] --- TrendDetector ---");
   double ramp[];
   BuildRamp(ramp, 120, 0.5);
   double ts = CTrendDetector::TrendStrength(ramp, 120);
   Check("ramp strength high", ts > 0.6, StringFormat("ts=%.3f", ts));
   Check("ramp direction +1", CTrendDetector::Direction(ramp, 120) == 1);

   double zg[];
   BuildZigzag(zg, 120, 1.0);
   ts = CTrendDetector::TrendStrength(zg, 120);
   Check("zigzag strength low", ts < 0.4, StringFormat("ts=%.3f", ts));
   Check("zigzag direction 0", CTrendDetector::Direction(zg, 120) == 0);
  }

void TestRangeDetector()
  {
   Print("[PHASE2] --- RangeDetector ---");
   double osc[];
   BuildOscillation(osc, 120, 1.0, 8);
   double rs = CRangeDetector::RangeScore(osc, 120);
   Check("oscillation range score high", rs > 0.5, StringFormat("rs=%.3f", rs));

   double ramp[];
   BuildRamp(ramp, 120, 0.5);
   rs = CRangeDetector::RangeScore(ramp, 120);
   Check("ramp range score low", rs < 0.3, StringFormat("rs=%.3f", rs));
  }

void TestCompressionExpansion()
  {
   Print("[PHASE2] --- Compression / Expansion ---");
   double c = CCompressionDetector::CompressionScore(0.05, 0.3);
   Check("compression at p=0.05 r=0.3 high", c > 0.6, StringFormat("c=%.3f", c));
   double e = CExpansionDetector::ExpansionScore(0.95, 3.0);
   Check("expansion at p=0.95 r=3.0 high", e > 0.6, StringFormat("e=%.3f", e));
  }

void TestTransitionDetector()
  {
   Print("[PHASE2] --- TransitionDetector ---");
   // Vol change must sit INSIDE the detector's 2*window view (last 20 pts
   // with window=10): 30 low-vol pts, then 10 low-vol, then 10 high-vol.
   double series[];
   ArrayResize(series, 50);
   double prev = 100.0;
   for(int i = 0; i < 30; i++) { series[i] = prev; prev += 0.1; }
   for(int i = 30; i < 40; i++) { series[i] = prev; prev += 0.1; }
   for(int i = 40; i < 50; i++) { series[i] = prev; prev += 0.5; }
   double tv = CTransitionDetector::TransitionScore(series, 50, 10);
   Check("vol-doubling transition high", tv > 0.4, StringFormat("trans=%.3f", tv));
  }

void TestHurst()
  {
   Print("[PHASE2] --- HurstAnalyzer ---");
   double rw[];
   BuildRandomWalk(rw, 512, 42);
   double h = CHurstAnalyzer::HurstOnCloses(rw, 512);
   Check("random walk H ~ 0.5", h > 0.35 && h < 0.65, StringFormat("H=%.3f", h));

   double pr[];
   BuildPersistent(pr, 512, 42);
   h = CHurstAnalyzer::HurstOnCloses(pr, 512);
   Check("persistent H > 0.6", h > 0.6, StringFormat("H=%.3f", h));

   double mr[];
   BuildMeanReverting(mr, 512, 42);
   h = CHurstAnalyzer::HurstOnCloses(mr, 512);
   Check("mean-reverting H < 0.4", h < 0.4, StringFormat("H=%.3f", h));
  }

void TestRegimeEngine()
  {
   Print("[PHASE2] --- RegimeEngine ---");
   CRegimeEngine re;
   double ramp[];
   BuildRamp(ramp, 120, 0.5);
   re.Classify(ramp, 120, 0.4, 1.0);
   Check("ramp -> TREND_UP", re.Regime() == REGIME_TREND_UP,
         StringFormat("got %s", RegimeToString(re.Regime())));
   Check("trend confidence > 0", re.Confidence() > 0.0, StringFormat("conf=%.3f", re.Confidence()));

   double osc[];
   BuildOscillation(osc, 120, 1.0, 8);
   re.Classify(osc, 120, 0.5, 1.0);
   Check("oscillation -> RANGE", re.Regime() == REGIME_RANGE,
         StringFormat("got %s", RegimeToString(re.Regime())));

   double flat[];
   BuildRamp(flat, 120, 0.0);          // constant closes
   re.Classify(flat, 120, 0.05, 0.3);
   Check("squeeze inputs -> COMPRESSION", re.Regime() == REGIME_COMPRESSION,
         StringFormat("got %s", RegimeToString(re.Regime())));

   // A monotonic ramp + burst resolves to TREND_UP (expansion WITH a trend is
   // a trend); EXPANSION wins only when vol bursts without a strong trend.
   re.Classify(osc, 120, 0.95, 3.0);
   Check("burst + no trend -> EXPANSION", re.Regime() == REGIME_EXPANSION,
         StringFormat("got %s", RegimeToString(re.Regime())));

   Check("confidence within (0,1]", re.Confidence() > 0.0 && re.Confidence() <= 1.0,
         StringFormat("conf=%.3f", re.Confidence()));
  }

//+------------------------------------------------------------------+
//| OnInit — run the suite                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[PHASE2] === MITEMSHUB Phase 2 unit tests starting ===");
   TestTimeframeManager();
   TestCandleEngine();
   TestTrendDetector();
   TestRangeDetector();
   TestCompressionExpansion();
   TestTransitionDetector();
   TestHurst();
   TestRegimeEngine();
   Print(StringFormat("[PHASE2] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail > 0)
     {
      Print("[PHASE2] SUITE FAILED — do not proceed to Phase 3");
      return(INIT_FAILED);
     }
   Print("[PHASE2] SUITE PASSED — Phase 2 complete");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
