//+------------------------------------------------------------------+
//|                                  Analytics/PerformanceAnalytics.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 PerformanceAnalytics.      |
//|                                                                  |
//|  Plan §18: computes the full performance metric set from an      |
//|  array of closed OutcomeRecords (the Phase-5/7 journal rows),    |
//|  and breaks it down by strategy, regime, direction, exit reason  |
//|  and confidence bucket — so the R-journal answers "which subset  |
//|  actually carries the edge".  Pure static math over the records, |
//|  testable headlessly (same pattern as PositionSizer / Stop).     |
//|                                                                  |
//|  Drawdown is measured on the cumulative-R curve (peak-to-trough, |
//|  stake-independent) — the same convention CPerformanceLogger     |
//|  maintains incrementally, so both aggregators agree by design.   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_ANALYTICS_PERFORMANCEANALYTICS_MQH
#define MITEMSHUB_ANALYTICS_PERFORMANCEANALYTICS_MQH

#include "../Core/Constants.mqh"
#include "../Journal/PerformanceLogger.mqh"

#define ANALYTICS_MAX_STRATEGIES 8
#define ANALYTICS_MAX_REGIMES    12
#define ANALYTICS_MAX_EXIT_REASONS 12   // EXIT_NONE .. EXIT_SESSION_END

//--- one bucket's aggregate -----------------------------------------------------
struct BucketStats
  {
   int    n;
   int    wins;
   double sum_r;

   void Reset()
     {
      n = 0;
      wins = 0;
      sum_r = 0.0;
     }
   double HitRate() const   { return(n > 0 ? (double)wins / (double)n : 0.0); }
   double AvgR() const      { return(n > 0 ? sum_r / (double)n : 0.0); }
  };

class CPerformanceAnalytics
  {
public:
   //--- §18 headline set over OutcomeRecord[] (identical math to the logger) ---
   static void Metrics(const OutcomeRecord &rows[], const int n,
                       PerformanceSummary &out)
     {
      out.Reset();
      double cum = 0.0, peak = 0.0;
      int streak = 0, streak_sign = 0;
      double sum_hold = 0.0, sum_win_r = 0.0, sum_loss_r = 0.0;
      for(int i = 0; i < n; i++)
        {
         OutcomeRecord o = rows[i];   // MQL5: no local reference variables
         out.trades++;
         out.sum_r += o.return_r;
         if(o.won)
           {
            out.wins++;
            sum_win_r += o.return_r;
            out.gross_profit += o.return_r;
           }
         else
           {
            out.losses++;
            sum_loss_r += o.return_r;
            out.gross_loss += -o.return_r;
           }
         int sign = o.won ? 1 : -1;
         if(sign == streak_sign) streak++;
         else
           {
            if(streak_sign > 0 && streak > out.max_consec_wins)
               out.max_consec_wins = streak;
            if(streak_sign < 0 && streak > out.max_consec_losses)
               out.max_consec_losses = streak;
            streak = 1;
            streak_sign = sign;
           }
         cum += o.return_r;
         if(cum > peak) peak = cum;
         double dd = peak - cum;
         if(dd > out.max_drawdown_r)
            out.max_drawdown_r = dd;
         sum_hold += o.hold_bars;
        }
      if(streak_sign > 0 && streak > out.max_consec_wins)
         out.max_consec_wins = streak;
      if(streak_sign < 0 && streak > out.max_consec_losses)
         out.max_consec_losses = streak;
      if(out.trades > 0)
        {
         out.win_rate   = (double)out.wins / (double)out.trades;
         out.avg_r      = out.sum_r / (double)out.trades;
         out.avg_win_r  = out.wins > 0 ? sum_win_r / (double)out.wins : 0.0;
         out.avg_loss_r = out.losses > 0 ? sum_loss_r / (double)out.losses : 0.0;
         out.avg_hold_bars = sum_hold / (double)out.trades;
         out.profit_factor = (out.gross_loss > 0.0)
                             ? out.gross_profit / out.gross_loss : 0.0;
        }
     }

   //--- per-strategy split --------------------------------------------------------
   static void SplitByStrategy(const OutcomeRecord &rows[], const int n,
                               BucketStats &out[])
     {
      for(int s = 0; s < ANALYTICS_MAX_STRATEGIES; s++)
         out[s].Reset();
      for(int i = 0; i < n; i++)
        {
         int s = (int)rows[i].strategy;
         if(s < 0 || s >= ANALYTICS_MAX_STRATEGIES)
            s = 0;
         BucketStats b = out[s];      // read-modify-write (no local refs)
         b.n++;
         b.sum_r += rows[i].return_r;
         if(rows[i].won)
            b.wins++;
         out[s] = b;
        }
     }

   //--- per-regime split ------------------------------------------------------------
   static void SplitByRegime(const OutcomeRecord &rows[], const int n,
                             BucketStats &out[])
     {
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
         out[r].Reset();
      for(int i = 0; i < n; i++)
        {
         int r = (int)rows[i].regime;
         if(r < 0 || r >= ANALYTICS_MAX_REGIMES)
            r = 0;
         BucketStats b = out[r];      // read-modify-write (no local refs)
         b.n++;
         b.sum_r += rows[i].return_r;
         if(rows[i].won)
            b.wins++;
         out[r] = b;
        }
     }

   //--- per-direction split (index 0 = long, 1 = short) -----------------------------
   static void SplitByDirection(const OutcomeRecord &rows[], const int n,
                                BucketStats &out[])
     {
      out[0].Reset();
      out[1].Reset();
      for(int i = 0; i < n; i++)
        {
         int d = rows[i].direction > 0 ? 0 : 1;
         BucketStats b = out[d];      // read-modify-write (no local refs)
         b.n++;
         b.sum_r += rows[i].return_r;
         if(rows[i].won)
            b.wins++;
         out[d] = b;
        }
     }

   //--- per-exit-reason split ---------------------------------------------------------
   static void SplitByExitReason(const OutcomeRecord &rows[], const int n,
                                 BucketStats &out[])
     {
      for(int r = 0; r < ANALYTICS_MAX_EXIT_REASONS; r++)
         out[r].Reset();
      for(int i = 0; i < n; i++)
        {
         int r = (int)rows[i].exit_reason;
         if(r < 0 || r >= ANALYTICS_MAX_EXIT_REASONS)
            r = (int)EXIT_STOP_HIT;
         BucketStats b = out[r];      // read-modify-write (no local refs)
         b.n++;
         b.sum_r += rows[i].return_r;
         if(rows[i].won)
            b.wins++;
         out[r] = b;
        }
     }

   //--- per-confidence bucket (parallel confidence array) -----------------------------
   // strong = confidence >= strong_threshold; weak = below.  The bucket stats are
   // filled in out[0] (weak) and out[1] (strong) so the STRONG vs WEAK discrimination
   // question the decision layer cares about is directly answerable.
   static void SplitByConfidence(const OutcomeRecord &rows[], const int n,
                                 const double &conf[], const double strong_threshold,
                                 BucketStats &out[])
     {
      out[0].Reset();
      out[1].Reset();
      for(int i = 0; i < n; i++)
        {
         int b = (conf[i] >= strong_threshold) ? 1 : 0;
         BucketStats bkt = out[b];    // read-modify-write (no local refs)
         bkt.n++;
         bkt.sum_r += rows[i].return_r;
         if(rows[i].won)
            bkt.wins++;
         out[b] = bkt;
        }
     }

   //--- plan §24 print ----------------------------------------------------------------
   static void PrintMetrics(const string label, const PerformanceSummary &m)
     {
      Print(StringFormat("[ANALYTICS] %s: %d trades (%dW/%dL) hit=%.1f%% "
                         "exp=%+.3fR sumR=%+.2f PF=%.2f maxDD=%.2fR "
                         "avgWin=%+.2fR avgLoss=%+.2fR winStreak=%d lossStreak=%d "
                         "avgHold=%.1fb",
                         label, m.trades, m.wins, m.losses, 100.0 * m.win_rate,
                         m.avg_r, m.sum_r, m.profit_factor, m.max_drawdown_r,
                         m.avg_win_r, m.avg_loss_r, m.max_consec_wins,
                         m.max_consec_losses, m.avg_hold_bars));
     }

   static void PrintBucket(const string label, const BucketStats &b)
     {
      Print(StringFormat("[ANALYTICS]   %-22s n=%4d hit=%5.1f%% exp=%+.3fR sumR=%+.2fR",
                         label, b.n, 100.0 * b.HitRate(), b.AvgR(), b.sum_r));
     }
  };

#endif // MITEMSHUB_ANALYTICS_PERFORMANCEANALYTICS_MQH
