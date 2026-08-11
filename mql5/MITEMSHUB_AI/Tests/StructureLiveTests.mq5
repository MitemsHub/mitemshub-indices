//+------------------------------------------------------------------+
//|                                  Tests/StructureLiveTests.mq5    |
//|  MITEMSHUB AI MARKET ENGINE — live structure cross-validation.   |
//|                                                                  |
//|  Streams M5 bars on the SYN75 chart INSIDE the MT5 Strategy      |
//|  Tester and compares, per closed bar:                            |
//|    - the reconciled CStructureEngine bias (Phase 3, sweep-fixed) |
//|    - CStructureParity direction — the faithful MQL5 port of the  |
//|      Python structural_direction (PythonParity/StructureParity,  |
//|      validated == real Python by mql5/structure_parity_check.py) |
//|    - the Phase-5 CConfidenceEngine.Gate verdict (strong/weak/    |
//|      wait) computed live from the structure path: setup quality  |
//|      = window structure-event density, formal setup = a BOS/     |
//|      CHOCH agreeing with the bias, composite via ScoringEngine.  |
//|      The gate's directional verdicts are compared against the    |
//|      same Python structural_direction — a second agreement axis. |
//|                                                                  |
//|  This is the "does the .mqh code actually match Python live"     |
//|  gate: the phase-3 real-corpus check compared the Python MIRROR  |
//|  of the engine; this suite exercises the real .mqh classes over  |
//|  the tester's own SYN75 M5 data.                                 |
//|                                                                  |
//|  Verdict format matches the Phase-1/2 harness pattern so         |
//|  verify_all.ps1 picks it up: `=== N passed, N failed ===` and    |
//|  `SUITE PASSED/FAILED` in the Experts log.                       |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB live structure cross-validation — SYN75 M5, engine vs Python parity"

#include "../Core/Constants.mqh"
#include "../Core/Config.mqh"
#include "../Core/StateManager.mqh"
#include "../Market/CandleEngine.mqh"
#include "../Structure/StructureEngine.mqh"
#include "../PythonParity/StructureParity.mqh"
#include "../Decision/ConfidenceEngine.mqh"
#include "../Decision/ScoringEngine.mqh"

input int InpMinAgreePct   = 70;   // PASS threshold on bias-vs-parity agreement
input int InpMinGateAgreePct = 65; // PASS threshold on gate-direction-vs-parity
input int InpLookback      = 100;  // bars the parity window uses (== structure window)

int g_pass = 0;
int g_fail = 0;
int g_total = 0;
int g_neutral_m = 0;    // MQL5 bias NEUTRAL windows
int g_neutral_p = 0;    // Python direction FLAT windows
int g_disagree_logged = 0;

//--- Phase-5 gate axis state --------------------------------------------------
int g_gate_pass = 0;        // gate directional verdict == Python direction
int g_gate_fail = 0;        // gate directional verdict != Python direction
int g_gate_flat_py = 0;     // gate directional, Python FLAT (documented semantic)
int g_gate_wait = 0;        // gate WAIT (incl. neutral engine bias)
int g_verdicts[5];          // SIGNAL_WAIT..SIGNAL_STRONG_SELL counts
int g_gate_disagree_logged = 0;

//+------------------------------------------------------------------+
//| OnInit — load M5 bars, stream both engines, print the verdict    |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[STRUCTLIVE] === StructureEngine vs Python structural_direction on SYN75 M5 starting ===");

   MqlRates rates[];
   int got = CopyRates(_Symbol, PERIOD_M5, 0, 50000, rates);
   if(got <= 0)
     {
      Print("[STRUCTLIVE] CopyRates(M5) failed, error=", GetLastError());
      Print("[STRUCTLIVE] SUITE FAILED — no M5 data in the tester");
      return(INIT_FAILED);
     }
   int n = got;
   if(n < InpLookback + 60)
     {
      Print(StringFormat("[STRUCTLIVE] not enough M5 history: %d bars (need >= %d)", n, InpLookback + 60));
      Print("[STRUCTLIVE] SUITE FAILED — insufficient tester history");
      return(INIT_FAILED);
     }
   Print(StringFormat("[STRUCTLIVE] loaded %d M5 bars on %s (window %d, swing 2/2)", n, _Symbol, InpLookback));

   CCandleEngine ce;
   ce.RegisterTimeframe(PERIOD_M5);
   CStructureEngine eng;
   eng.SetParams(2, 2, InpLookback);
   CStructureParity parity;

   // rolling parity window (oldest-first), sized to InpLookback
   double winO[], winH[], winL[], winC[];
   ArrayResize(winO, InpLookback);
   ArrayResize(winH, InpLookback);
   ArrayResize(winL, InpLookback);
   ArrayResize(winC, InpLookback);
   for(int j = 0; j < InpLookback; j++)
     {
      winO[j] = 0.0; winH[j] = 0.0; winL[j] = 0.0; winC[j] = 0.0;
     }

   for(int k = 0; k < n; k++)
     {
      MqlRates r = rates[k];
      ce.PushBar(PERIOD_M5, r.open, r.high, r.low, r.close, r.time);
      // shift the parity window and append the new bar
      for(int j = 0; j < InpLookback - 1; j++)
        {
         winO[j] = winO[j + 1];
         winH[j] = winH[j + 1];
         winL[j] = winL[j + 1];
         winC[j] = winC[j + 1];
        }
      winO[InpLookback - 1] = r.open;
      winH[InpLookback - 1] = r.high;
      winL[InpLookback - 1] = r.low;
      winC[InpLookback - 1] = r.close;

      if(k < InpLookback - 1)
         continue;

      StructureParityResult p;
      parity.Compute(winO, winH, winL, winC, InpLookback, p);
      double atr_now = p.displacement_atr > 0.0 ? p.displacement_atr
                       : (r.high - r.low);   // degenerate guard — engine uses ATR as a scale only
      if(!eng.Update(ce, PERIOD_M5, atr_now))
         continue;
      int mb = (eng.Bias() == STRUCT_BIAS_BULLISH) ? 1 :
                (eng.Bias() == STRUCT_BIAS_BEARISH ? -1 : 0);   // enum: NEUTRAL=0, BULLISH=1, BEARISH=2
      int pd = p.direction;         // +1 / -1 / 0

      g_total++;
      if(mb == pd)
         g_pass++;
      else
        {
         g_fail++;
         if(g_disagree_logged < 12)
           {
            g_disagree_logged++;
            Print(StringFormat("[STRUCTLIVE] DISAGREE bar %d %s close %.2f: engine bias=%d parity dir=%d",
                               k, TimeToString(r.time, TIME_DATE | TIME_MINUTES), r.close, mb, pd));
           }
        }
      if(mb == 0) g_neutral_m++;
      if(pd == 0) g_neutral_p++;

      //--- Phase-5 decision layer: score + gate the live structure/bias path ---
      if(mb == 0)
        {
         // no direction from the structure engine -> the gate stands aside
         g_verdicts[SIGNAL_WAIT]++;
         g_gate_wait++;
        }
      else
        {
         bool is_long = (mb == 1);
         // formal setup: a BOS/CHOCH whose event direction agrees with the bias
         int last_ev = eng.LastEvent();
         int last_dir = eng.LastEventDirection();
         bool has_setup = (last_ev == STRUCT_EVENT_BOS || last_ev == STRUCT_EVENT_CHOCH)
                          && last_dir == (is_long ? 1 : -1);
         // setup quality from structure-event density in the window
         // (detector arrays are rebuilt per Update, so the counts are per-window)
         double ev = (double)(eng.BOSCount() + eng.CHOCHCount());
         double density = MathMin(1.0, ev / (InpLookback * 0.15));
         double setup_q = 0.5 + 0.5 * density;

         // ScoreBreakdown for the structure path (no geometry/regime here):
         // regime_score 1.0 (UNKNOWN==UNKNOWN — no regime info on this path),
         // structure_score 1.0 (the engine's own bias is the direction),
         // risk 0.5 neutral (no levels), execution 1.0 (tester data).
         ScoreBreakdown sb;
         sb.setup_score     = setup_q;
         sb.regime_score    = 1.0;
         sb.structure_score = 1.0;
         sb.risk_score      = 0.5;
         sb.execution_score = 1.0;
         sb.composite = CScoringEngine::Composite(sb.setup_score, sb.regime_score,
                                                  sb.structure_score, sb.risk_score,
                                                  sb.execution_score);
         // No calibration in the tester (samples=0 -> base min 0.48), no drift
         // detector (steps >= decay window -> 0 penalty).
         double minc = 0.0;
         ENUM_SIGNAL_STRENGTH sig = CConfidenceEngine::Gate(sb.composite, setup_q,
                                                            has_setup, is_long,
                                                            -1.0, 0, 5000, minc);
         g_verdicts[sig]++;
         if(sig == SIGNAL_WAIT)
            g_gate_wait++;
         else
           {
            int gdir = (sig == SIGNAL_STRONG_BUY || sig == SIGNAL_WEAK_BUY) ? 1 : -1;
            if(pd == 0)
               g_gate_flat_py++;
            else if(gdir == pd)
               g_gate_pass++;
            else
              {
               g_gate_fail++;
               if(g_gate_disagree_logged < 12)
                 {
                  g_gate_disagree_logged++;
                  Print(StringFormat("[STRUCTLIVE] GATE DISAGREE bar %d %s close %.2f: %s vs python dir=%d "
                                     "(comp=%.2f setup=%.2f setup_ok=%s)",
                                     k, TimeToString(r.time, TIME_DATE | TIME_MINUTES), r.close,
                                     SignalStrengthToString(sig), pd, sb.composite, setup_q,
                                     has_setup ? "yes" : "no"));
                 }
              }
           }
        }
     }

   if(g_total == 0)
     {
      Print("[STRUCTLIVE] SUITE FAILED — no comparison bars produced");
      return(INIT_FAILED);
     }

   double agree = 100.0 * (double)g_pass / g_total;
   Print(StringFormat("[STRUCTLIVE] compared %d bars, agreement %.1f%% (engine-neutral %d, python-flat %d)",
                      g_total, agree, g_neutral_m, g_neutral_p));

   //--- Phase-5 gate axis report ----------------------------------------------
   int g_dir = g_gate_pass + g_gate_fail + g_gate_flat_py;
   double gate_agree = (g_gate_pass + g_gate_fail) > 0
                       ? 100.0 * (double)g_gate_pass / (g_gate_pass + g_gate_fail) : 0.0;
   Print(StringFormat("[STRUCTLIVE] gate verdicts: strong_buy=%d weak_buy=%d wait=%d "
                      "weak_sell=%d strong_sell=%d",
                      g_verdicts[SIGNAL_STRONG_BUY], g_verdicts[SIGNAL_WEAK_BUY],
                      g_verdicts[SIGNAL_WAIT], g_verdicts[SIGNAL_WEAK_SELL],
                      g_verdicts[SIGNAL_STRONG_SELL]));
   Print(StringFormat("[STRUCTLIVE] gate vs python: directional=%d agree=%d disagree=%d "
                      "python-flat=%d wait=%d  agreement %.1f%%",
                      g_dir, g_gate_pass, g_gate_fail, g_gate_flat_py, g_gate_wait,
                      gate_agree));

   Print(StringFormat("[STRUCTLIVE] === %d passed, %d failed ===  (bias %.1f%% + gate %.1f%% on %s M5)",
                      g_pass, g_fail, agree, gate_agree, _Symbol));
   bool ok_bias = (g_fail > 0 && agree < (double)InpMinAgreePct) ? false : true;
   bool ok_gate = (g_gate_fail > 0 && gate_agree < (double)InpMinGateAgreePct) ? false : true;
   if(!ok_bias)
     {
      Print(StringFormat("[STRUCTLIVE] SUITE FAILED — bias agreement %.1f%% below threshold %d%%", agree, InpMinAgreePct));
      return(INIT_FAILED);
     }
   if(!ok_gate)
     {
      Print(StringFormat("[STRUCTLIVE] SUITE FAILED — gate agreement %.1f%% below threshold %d%%", gate_agree, InpMinGateAgreePct));
      return(INIT_FAILED);
     }
   Print("[STRUCTLIVE] SUITE PASSED — reconciled engine + decision gate agree with Python structural_direction live on SYN75");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
