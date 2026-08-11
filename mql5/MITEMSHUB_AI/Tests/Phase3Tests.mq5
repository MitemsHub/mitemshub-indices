//+------------------------------------------------------------------+
//|                                       Tests/Phase3Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 3 unit tests.                |
//|                                                                  |
//|  Covers: SwingDetector, BOSDetector, CHOCHDetector,              |
//|  LiquidityEngine, SupportResistance, DisplacementDetector,       |
//|  and the StructureEngine aggregator consuming the Phase-2        |
//|  CandleEngine.                                                   |
//|                                                                  |
//|  Mirrors mql5/phase3_logic_check.py assertion-for-assertion.     |
//|  Run: attach to any chart; OnInit runs the suite and reports     |
//|  PASS/FAIL to the log (INIT_FAILED if any test fails).           |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 3 unit tests — Structure"

#include "../Core/Constants.mqh"
#include "../Market/CandleEngine.mqh"
#include "../Structure/SwingDetector.mqh"
#include "../Structure/BOSDetector.mqh"
#include "../Structure/CHOCHDetector.mqh"
#include "../Structure/LiquidityEngine.mqh"
#include "../Structure/SupportResistance.mqh"
#include "../Structure/DisplacementDetector.mqh"
#include "../Structure/StructureEngine.mqh"

//--- test counters -----------------------------------------------------------
int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE3] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE3] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

//--- Crafted series helpers ---------------------------------------------------
void BuildFromCloses(const double &closes[], const int n, const double off,
                     double &opens[], double &highs[], double &lows[], datetime &times[],
                     const datetime t0)
  {
   ArrayResize(opens,  n);
   ArrayResize(highs,  n);
   ArrayResize(lows,   n);
   ArrayResize(times,  n);
   for(int i = 0; i < n; i++)
     {
      opens[i] = (i == 0) ? closes[0] : closes[i - 1];
      highs[i] = closes[i] + off;
      lows[i]  = closes[i] - off;
      times[i] = (datetime)(t0 + i);
     }
  }

//+------------------------------------------------------------------+
//| Test groups                                                       |
//+------------------------------------------------------------------+
void TestSwingDetector()
  {
   Print("[PHASE3] --- SwingDetector ---");
   double v_highs[] = {100, 101, 102, 103, 104, 103, 102, 101, 100};
   double v_lows[]  = {104, 103, 102, 101, 100, 101, 102, 103, 104};
   Check("peak is swing high", CSwingDetector::IsSwingHigh(v_highs, 4, 2, 2));
   Check("slope not swing high", !CSwingDetector::IsSwingHigh(v_highs, 2, 2, 2));
   Check("edge guard left", !CSwingDetector::IsSwingHigh(v_highs, 0, 2, 2));
   Check("valley is swing low", CSwingDetector::IsSwingLow(v_lows, 4, 2, 2));
   Check("slope not swing low", !CSwingDetector::IsSwingLow(v_lows, 2, 2, 2));
   Check("deep peak strength 1.0",
         CloseEnough(CSwingDetector::Strength(v_highs, v_lows, 4, 1, 1.0), 1.0));
   double shallow_h[] = {100, 100.5, 101, 100.5, 100};
   double shallow_l[] = {99.5, 100.0, 100.5, 100.0, 99.5};
   Check("shallow peak strength 0.5",
         CloseEnough(CSwingDetector::Strength(shallow_h, shallow_l, 2, 1, 1.0), 0.5));

   double saw[] = {100, 101, 102, 103, 102, 101, 100, 101, 102, 103, 102, 101, 100};
   double o_saw[], h_saw[], l_saw[];
   datetime t_saw[];
   BuildFromCloses(saw, 13, 0.5, o_saw, h_saw, l_saw, t_saw, 1000);
   SwingPoint sw[];
   int nsw = CSwingDetector::FindSwing(h_saw, l_saw, t_saw, 13, 2, 2, 2.0, sw, 64);
   Check("sawtooth swing count 3", nsw == 3, StringFormat("got %d", nsw));
   bool alt = (nsw == 3) && sw[0].direction == 1 && sw[1].direction == -1 && sw[2].direction == 1;
   Check("swing directions alternate", alt);
   Check("sawtooth swing strength 0.5", CloseEnough(sw[0].strength, 0.5),
         StringFormat("%.3f", sw[0].strength));
   Check("swing bar indices", nsw == 3 && sw[0].bar == 3 && sw[1].bar == 6 && sw[2].bar == 9,
         StringFormat("%d/%d/%d", sw[0].bar, sw[1].bar, sw[2].bar));
  }

void TestBOSDetector()
  {
   Print("[PHASE3] --- BOSDetector ---");
   double bos_closes[] = {100, 101, 102, 103, 104, 103, 102, 106};
   double o_b[], h_b[], l_b[];
   datetime t_b[];
   BuildFromCloses(bos_closes, 8, 0.5, o_b, h_b, l_b, t_b, 1000);
   BOSEvent bos[];
   int nb = CBOSDetector::Detect(h_b, l_b, bos_closes, t_b, 8, 2, 2, 1.0, bos, 16);
   Check("bullish BOS count 1", nb == 1, StringFormat("got %d", nb));
   Check("bullish BOS direction +1", nb == 1 && bos[0].direction == 1);
   Check("bullish BOS at break bar", nb == 1 && bos[0].time == (datetime)1007);
   Check("bullish BOS level 104.5", nb == 1 && CloseEnough(bos[0].level, 104.5));
   Check("bullish BOS strength clamped 1.0", nb == 1 && CloseEnough(bos[0].strength, 1.0));

   double no_break[] = {100, 101, 102, 103, 104, 103, 102, 103};
   double o_n[], h_n[], l_n[];
   datetime t_n[];
   BuildFromCloses(no_break, 8, 0.5, o_n, h_n, l_n, t_n, 1000);
   Check("no BOS without break",
         CBOSDetector::Detect(h_n, l_n, no_break, t_n, 8, 2, 2, 1.0, bos, 16) == 0);

   double bear_closes[] = {100, 99, 98, 97, 96, 97, 98, 94};
   double o_br[], h_br[], l_br[];
   datetime t_br[];
   BuildFromCloses(bear_closes, 8, 0.5, o_br, h_br, l_br, t_br, 1000);
   int nb2 = CBOSDetector::Detect(h_br, l_br, bear_closes, t_br, 8, 2, 2, 1.0, bos, 16);
   Check("bearish BOS direction -1", nb2 == 1 && bos[0].direction == -1,
         StringFormat("got %d", nb2));
  }

void TestCHOCHDetector()
  {
   Print("[PHASE3] --- CHOCHDetector ---");
   double down[] = {100, 103, 106, 104, 102, 104, 106, 108, 106.5, 105, 106.5, 107.5, 104};
   double o_c[], h_c[], l_c[];
   datetime t_c[];
   BuildFromCloses(down, 13, 0.5, o_c, h_c, l_c, t_c, 1000);
   CHOCH cd[];
   int nc = CCHOCHDetector::Detect(h_c, l_c, down, t_c, 13, 2, 2, 1.0, cd, 16);
   Check("CHOCH down count 1", nc == 1, StringFormat("got %d", nc));
   Check("CHOCH down direction -1", nc == 1 && cd[0].direction == -1);
   Check("CHOCH down at bar 12", nc == 1 && cd[0].time == (datetime)1012);
   Check("CHOCH down level = last HL 104.5", nc == 1 && CloseEnough(cd[0].level, 104.5));
   Check("CHOCH down strength 0.5", nc == 1 && CloseEnough(cd[0].strength, 0.5));

   double ramp[14];
   for(int i = 0; i < 14; i++)
      ramp[i] = 100.0 + i;
   double o_r[], h_r[], l_r[];
   datetime t_r[];
   BuildFromCloses(ramp, 14, 0.5, o_r, h_r, l_r, t_r, 1000);
   Check("no CHOCH on monotonic ramp",
         CCHOCHDetector::Detect(h_r, l_r, ramp, t_r, 14, 2, 2, 1.0, cd, 16) == 0);

   double up[] = {100, 97, 94, 96, 98, 96, 94, 92, 93.5, 95, 93.5, 92.5, 96};
   double o_u[], h_u[], l_u[];
   datetime t_u[];
   BuildFromCloses(up, 13, 0.5, o_u, h_u, l_u, t_u, 1000);
   int nu = CCHOCHDetector::Detect(h_u, l_u, up, t_u, 13, 2, 2, 1.0, cd, 16);
   Check("CHOCH up count 1", nu == 1, StringFormat("got %d", nu));
   Check("CHOCH up direction +1", nu == 1 && cd[0].direction == 1);
   Check("CHOCH up level = last LH 95.5", nu == 1 && CloseEnough(cd[0].level, 95.5));
  }

void TestLiquidityEngine()
  {
   Print("[PHASE3] --- LiquidityEngine ---");
   Check("buy-side sweep true", CLiquidityEngine::IsSweep(111.5, 108.0, 109.2, 110.5, 1.0, 0.1, true));

   // Phase-3 reconciliation: only the most recent swing of each polarity is
   // the live liquidity reference.  H1=110.5 (bar 2) is swept by bar 10's
   // wick to 111.5, but H2=113.5 (bar 7) is the newest high and is NOT
   // swept — the detector must report nothing (the old window-scan fired
   // on every 100-bar window of the real corpus: 448/448).
   double h_st[] = {105.5, 107.5, 110.5, 109.9, 108.5, 109.5, 111.5, 113.5, 112.5, 111.5, 111.5, 110.5};
   double l_st[] = {104.5, 106.5, 109.5, 107.5, 105.5, 108.5, 110.5, 112.5, 111.0, 110.0, 108.5, 109.5};
   double c_st[] = {105.0, 107.0, 110.0, 108.0, 106.0, 109.0, 111.0, 113.0, 111.5, 110.5, 109.2, 110.0};
   datetime t_st[12];
   for(int i = 0; i < 12; i++)
      t_st[i] = (datetime)(1000 + i);
   Sweep swp_st[];
   int ns_st = CLiquidityEngine::DetectSweeps(h_st, l_st, c_st, t_st, 12, 2, 2, 1.0, swp_st, 16, 0.1);
   Check("stale-level sweep ignored", ns_st == 0, StringFormat("got %d", ns_st));

   // Control: same setup but bar 10 wicks ABOVE the newest high (114.5) and
   // closes back inside -> one sweep of H2=113.5.
   double h_ct[] = {105.5, 107.5, 110.5, 109.9, 108.5, 109.5, 111.5, 113.5, 112.5, 111.5, 114.5, 110.5};
   double l_ct[] = {104.5, 106.5, 109.5, 107.5, 105.5, 108.5, 110.5, 112.5, 111.0, 110.0, 109.0, 109.5};
   double c_ct[] = {105.0, 107.0, 110.0, 108.0, 106.0, 109.0, 111.0, 113.0, 111.5, 110.5, 112.8, 110.0};
   Sweep swp_ct[];
   int ns_ct = CLiquidityEngine::DetectSweeps(h_ct, l_ct, c_ct, t_st, 12, 2, 2, 1.0, swp_ct, 16, 0.1);
   bool ctrl_ok = ns_ct == 1 && CloseEnough(swp_ct[0].level, 113.5) &&
                  swp_ct[0].direction == -1 && CloseEnough(swp_ct[0].extreme, 114.5);
   Check("newest-level sweep fires", ctrl_ok, StringFormat("got %d", ns_ct));
   Check("breakout close not a sweep", !CLiquidityEngine::IsSweep(111.5, 108.0, 111.2, 110.5, 1.0, 0.1, true));
   Check("no-exceed not a sweep", !CLiquidityEngine::IsSweep(109.8, 108.0, 109.2, 110.5, 1.0, 0.1, true));
   Check("wick must exceed min ATR", !CLiquidityEngine::IsSweep(110.55, 108.0, 109.2, 110.5, 1.0, 0.1, true));
   Check("sell-side sweep true", CLiquidityEngine::IsSweep(102.5, 98.2, 100.5, 99.5, 1.0, 0.1, false));

   // buy-side sweep: swing high 110.5 at bar 2; bar 8 wicks 111.5, closes 109.2
   double h_s1[] = {105.5, 107.5, 110.5, 109.9, 108.5, 109.5, 109.5, 108.5, 111.5, 110.0};
   double l_s1[] = {99.5, 104.5, 106.5, 107.5, 105.5, 105.5, 106.5, 106.5, 108.0, 108.5};
   double c_s1[] = {105.0, 107.0, 110.0, 108.0, 106.0, 109.0, 107.0, 108.0, 109.2, 109.5};
   datetime t_s1[10];
   for(int i = 0; i < 10; i++)
      t_s1[i] = (datetime)(1000 + i);
   Sweep swp[];
   int ns = CLiquidityEngine::DetectSweeps(h_s1, l_s1, c_s1, t_s1, 10, 2, 2, 1.0, swp, 16, 0.1);
   Check("buy-side sweep detected", ns == 1, StringFormat("got %d", ns));
   Check("buy-side sweep direction -1", ns == 1 && swp[0].direction == -1);
   Check("buy-side sweep level 110.5", ns == 1 && CloseEnough(swp[0].level, 110.5));
   Check("buy-side sweep extreme 111.5", ns == 1 && CloseEnough(swp[0].extreme, 111.5));
   Check("buy-side sweep at bar 8", ns == 1 && swp[0].time == (datetime)1008);

   // sell-side sweep: swing low 99.5 at bar 2; bar 7 wicks 98.2, closes 100.5
   double h_s2[] = {105.5, 103.5, 100.5, 101.5, 103.0, 101.0, 102.5, 102.5, 101.0};
   double l_s2[] = {104.5, 102.5, 99.5, 100.5, 102.0, 100.0, 101.5, 98.2, 99.5};
   double c_s2[] = {105.0, 103.0, 100.0, 101.0, 102.5, 100.5, 102.0, 100.5, 100.8};
   datetime t_s2[9];
   for(int i = 0; i < 9; i++)
      t_s2[i] = (datetime)(1000 + i);
   Sweep swp2[];
   int ns2 = CLiquidityEngine::DetectSweeps(h_s2, l_s2, c_s2, t_s2, 9, 2, 2, 1.0, swp2, 16, 0.1);
   Check("sell-side sweep detected", ns2 == 1, StringFormat("got %d", ns2));
   Check("sell-side sweep direction +1", ns2 == 1 && swp2[0].direction == 1);
   Check("sell-side sweep extreme 98.2", ns2 == 1 && CloseEnough(swp2[0].extreme, 98.2));
  }

void TestSupportResistance()
  {
   Print("[PHASE3] --- SupportResistance ---");
   double prices[] = {100, 100.1, 101, 99.9};
   int    kinds[]  = {1, -1, 1, -1};
   datetime times4[] = {(datetime)0, (datetime)1, (datetime)2, (datetime)3};
   SRLevel lvl[];
   int nl = CSupportResistance::Cluster(prices, kinds, times4, 4, 1.0, 0.25, lvl, 32, 2);
   Check("cluster keeps 1 level", nl == 1, StringFormat("got %d", nl));
   Check("cluster level ~100", nl == 1 && CloseEnough(lvl[0].level, 100.0));
   Check("cluster touches 3", nl == 1 && lvl[0].touches == 3, StringFormat("%d", lvl[0].touches));
   Check("cluster kind mixed -> -1", nl == 1 && lvl[0].kind == -1, StringFormat("%d", lvl[0].kind));
   double ql = 0.0;
   int qt = 0;
   bool q = CSupportResistance::QueryNear(lvl, nl, 100.2, 1.0, 0.25, ql, qt);
   Check("query near finds level", q && CloseEnough(ql, 100.0) && qt == 3);
   double ql2 = 0.0;
   int qt2 = 0;
   Check("query outside tolerance misses",
         !CSupportResistance::QueryNear(lvl, nl, 102.0, 1.0, 0.25, ql2, qt2));
  }

void TestDisplacementDetector()
  {
   Print("[PHASE3] --- DisplacementDetector ---");
   Check("big up bar is displacement",
         CDisplacementDetector::IsDisplacement(100, 104, 99, 103.8, 0.5, 2.0, 3.0));
   double o1[] = {100}, h1[] = {104}, l1[] = {99}, c1[] = {103.8};
   datetime t1[] = {(datetime)0};
   Displacement d1[];
   CDisplacementDetector::Detect(o1, h1, l1, c1, t1, 1, 0.5, d1, 16, 2.0, 3.0);
   Check("big up direction +1", ArraySize(d1) == 1 && d1[0].direction == 1);
   Check("big up score 1.0",
         CloseEnough(CDisplacementDetector::Score(100, 104, 99, 103.8, 0.5, 2.0, 3.0), 1.0));
   Check("small bar not displacement",
         !CDisplacementDetector::IsDisplacement(100, 100.6, 99.4, 100.5, 0.5, 2.0, 3.0));
   // 0.7*min(1, body_atr/2) + 0.3*min(1, range_atr/3) with body_atr=1.0, range_atr=2.4
   Check("small bar score 0.59",
         CloseEnough(CDisplacementDetector::Score(100, 100.6, 99.4, 100.5, 0.5, 2.0, 3.0), 0.59));
   Check("big down bar is displacement",
         CDisplacementDetector::IsDisplacement(100, 101, 95, 95.5, 0.5, 2.0, 3.0));
   double o2[] = {100}, h2[] = {101}, l2[] = {95}, c2[] = {95.5};
   datetime t2[] = {(datetime)0};
   Displacement d2[];
   CDisplacementDetector::Detect(o2, h2, l2, c2, t2, 1, 0.5, d2, 16, 2.0, 3.0);
   Check("big down direction -1", ArraySize(d2) == 1 && d2[0].direction == -1);
   Check("mid-close not displacement",
         !CDisplacementDetector::IsDisplacement(100, 104, 99, 101.5, 0.5, 2.0, 3.0));
  }

void TestStructureEngine()
  {
   Print("[PHASE3] --- StructureEngine (CandleEngine consumer) ---");
   CStructureEngine eng;
   eng.SetParams(2, 2, 32);
   CCandleEngine ce;
   ce.RegisterTimeframe(PERIOD_M5);

   Check("engine min-bars guard", !eng.Update(ce, PERIOD_M5, 1.0));

   // BOS series -> bullish bias
   double bos_closes[] = {100, 101, 102, 103, 104, 103, 102, 106, 105, 106.5};
   for(int i = 0; i < 10; i++)
      ce.PushBar(PERIOD_M5, bos_closes[i] - 0.5, bos_closes[i] + 0.5, bos_closes[i] - 0.5,
                 bos_closes[i], (datetime)(2000 + i));
   Check("engine BOS update ok", eng.Update(ce, PERIOD_M5, 1.0));
   Check("engine BOS bias BULLISH", eng.Bias() == STRUCT_BIAS_BULLISH,
         StringFormat("bias=%d", eng.Bias()));
   Check("engine BOS last event BOS", eng.LastEvent() == STRUCT_EVENT_BOS,
         StringFormat("ev=%d", eng.LastEvent()));
   Check("engine BOS direction +1", eng.LastEventDirection() == 1);
   Check("engine swings detected", eng.SwingCount() >= 1, StringFormat("%d", eng.SwingCount()));

   // sweep series -> sweep event (no BOS/CHOCH, so bias falls back to swings)
   CCandleEngine ce3;
   ce3.RegisterTimeframe(PERIOD_M5);
   double h_s[] = {105.5, 107.5, 110.5, 109.9, 108.5, 109.5, 109.5, 108.5, 111.5, 110.0};
   double l_s[] = {99.5, 104.5, 106.5, 107.5, 105.5, 105.5, 106.5, 106.5, 108.0, 108.5};
   double c_s[] = {105.0, 107.0, 110.0, 108.0, 106.0, 109.0, 107.0, 108.0, 109.2, 109.5};
   for(int i = 0; i < 10; i++)
      ce3.PushBar(PERIOD_M5, c_s[i] - 0.5, h_s[i], l_s[i], c_s[i], (datetime)(3000 + i));
   Check("engine sweep update ok", eng.Update(ce3, PERIOD_M5, 1.0));
   Check("engine sweep count >= 1", eng.SweepCount() >= 1, StringFormat("%d", eng.SweepCount()));
   Check("engine sweep last event", eng.LastEvent() == STRUCT_EVENT_SWEEP,
         StringFormat("ev=%d", eng.LastEvent()));
   Check("engine sweep direction -1", eng.LastEventDirection() == -1);

   // CHOCH series -> bearish bias (CHOCH at bar 12 outranks the BOS at bar 7)
   CCandleEngine ce4;
   ce4.RegisterTimeframe(PERIOD_M5);
   double down[] = {100, 103, 106, 104, 102, 104, 106, 108, 106.5, 105, 106.5, 107.5, 104};
   for(int i = 0; i < 13; i++)
      ce4.PushBar(PERIOD_M5, down[i] - 0.5, down[i] + 0.5, down[i] - 0.5,
                  down[i], (datetime)(4000 + i));
   Check("engine CHOCH update ok", eng.Update(ce4, PERIOD_M5, 1.0));
   Check("engine CHOCH bias BEARISH", eng.Bias() == STRUCT_BIAS_BEARISH,
         StringFormat("bias=%d", eng.Bias()));
   Check("engine CHOCH last event CHOCH", eng.LastEvent() == STRUCT_EVENT_CHOCH,
         StringFormat("ev=%d", eng.LastEvent()));
   Check("engine CHOCH direction -1", eng.LastEventDirection() == -1);
  }

//+------------------------------------------------------------------+
//| OnInit — run the suite                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[PHASE3] === MITEMSHUB Phase 3 unit tests starting ===");
   TestSwingDetector();
   TestBOSDetector();
   TestCHOCHDetector();
   TestLiquidityEngine();
   TestSupportResistance();
   TestDisplacementDetector();
   TestStructureEngine();
   Print(StringFormat("[PHASE3] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail > 0)
     {
      Print("[PHASE3] SUITE FAILED — do not proceed to Phase 4");
      return(INIT_FAILED);
     }
   Print("[PHASE3] SUITE PASSED — Phase 3 complete");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
