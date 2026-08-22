//+------------------------------------------------------------------+
//|                                    Analytics/ExpectancyEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 ExpectancyEngine.          |
//|                                                                  |
//|  The statistical core of the R-journal: expectancy, hit rate,    |
//|  average realized/planned RR, and the empirical break-even       |
//|  hit-rate floor — the "is this setup historically favorable      |
//|  relative to its invalidation?" question (plan §11 / §18).       |
//|                                                                  |
//|  Break-even math is the exact stage3_gate.py port (locked by the |
//|  parity gate, duplicated in CTradeQualityEngine::BreakEvenFloor): |
//|      floor = 1 / (1 + reward_risk) + margin, clamped [0.10, 0.60],|
//|      falls back to 0.50 when RR is unknown.                      |
//|  A strategy whose realized hit rate clears its own geometry's    |
//|  break-even floor is BEATING the floor; below it, the setup is   |
//|  statistically unfavorable no matter how it feels on the chart.  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_ANALYTICS_EXPECTANCYENGINE_MQH
#define MITEMSHUB_ANALYTICS_EXPECTANCYENGINE_MQH

#include "../Core/Constants.mqh"
#include "../Decision/TradeQualityEngine.mqh"

//--- a per-strategy expectancy verdict (the Stage-3 gate shape) -----------------
struct ExpectancyVerdict
  {
   int    n;              // closed trades
   double hit_rate;       // 0..1
   double avg_r;          // expectancy in R (gross)
   double avg_rr;         // average PLANNED reward/risk
   double break_even_floor;
   bool   beats_floor;
   bool   enough_samples; // n >= min_samples
  };

class CExpectancyEngine
  {
public:
   //--- stage3_gate.py parity (same formula as CTradeQualityEngine) -------------
   static double BreakEvenFloor(const double reward_risk, const double margin)
     {
      return(CTradeQualityEngine::BreakEvenFloor(reward_risk, margin));
     }

   //--- aggregate an OutcomeRecord[] into a verdict ------------------------------
   static void Verdict(const OutcomeRecord &rows[], const int n,
                       const int min_samples, const double margin,
                       ExpectancyVerdict &out)
     {
      out.n = 0;
      out.hit_rate = 0.0;
      out.avg_r = 0.0;
      out.avg_rr = 0.0;
      out.break_even_floor = GATE_HIT_RATE_FLOOR_DEFAULT;
      out.beats_floor = false;
      out.enough_samples = false;
      if(n <= 0)
         return;
      double sum_r = 0.0, sum_rr = 0.0;
      int wins = 0;
      for(int i = 0; i < n; i++)
        {
         OutcomeRecord o = rows[i];   // MQL5: no local reference variables
         sum_r += o.return_r;
         sum_rr += o.reward_risk;
         if(o.won)
            wins++;
        }
      out.n = n;
      out.hit_rate = (double)wins / (double)n;
      out.avg_r = sum_r / (double)n;
      out.avg_rr = sum_rr / (double)n;
      out.break_even_floor = BreakEvenFloor(out.avg_rr, margin);
      out.enough_samples = (n >= min_samples);
      out.beats_floor = out.enough_samples && (out.hit_rate >= out.break_even_floor);
     }

   //--- verdict over a single strategy's records (filter inside, no copy) ----------
   static void VerdictForStrategy(const OutcomeRecord &rows[], const int n,
                                  const ENUM_STRATEGY strategy,
                                  const int min_samples, const double margin,
                                  ExpectancyVerdict &out)
     {
      out.n = 0;
      out.hit_rate = 0.0;
      out.avg_r = 0.0;
      out.avg_rr = 0.0;
      out.break_even_floor = GATE_HIT_RATE_FLOOR_DEFAULT;
      out.beats_floor = false;
      out.enough_samples = false;
      double sum_r = 0.0, sum_rr = 0.0;
      int wins = 0;
      for(int i = 0; i < n; i++)
        {
         if(strategy != STRATEGY_NONE && rows[i].strategy != strategy)
            continue;
         out.n++;
         sum_r += rows[i].return_r;
         sum_rr += rows[i].reward_risk;
         if(rows[i].won)
            wins++;
        }
      if(out.n == 0)
         return;
      out.hit_rate = (double)wins / (double)out.n;
      out.avg_r = sum_r / (double)out.n;
      out.avg_rr = sum_rr / (double)out.n;
      out.break_even_floor = BreakEvenFloor(out.avg_rr, margin);
      out.enough_samples = (out.n >= min_samples);
      out.beats_floor = out.enough_samples
                        && (out.hit_rate >= out.break_even_floor);
     }

   //--- simple helpers -------------------------------------------------------------
   static double HitRate(const OutcomeRecord &rows[], const int n)
     {
      if(n <= 0)
         return(0.0);
      int wins = 0;
      for(int i = 0; i < n; i++)
         if(rows[i].won)
            wins++;
      return((double)wins / (double)n);
     }

   static double AvgR(const OutcomeRecord &rows[], const int n)
     {
      if(n <= 0)
         return(0.0);
      double sum = 0.0;
      for(int i = 0; i < n; i++)
         sum += rows[i].return_r;
      return(sum / (double)n);
     }

   static string VerdictString(const ExpectancyVerdict &v)
     {
      return(StringFormat("n=%d hit=%.1f%% floor=%.1f%% -> %s",
                          v.n, 100.0 * v.hit_rate, 100.0 * v.break_even_floor,
                          v.beats_floor ? "BEATS" : "does NOT beat"));
     }
  };

#endif // MITEMSHUB_ANALYTICS_EXPECTANCYENGINE_MQH
