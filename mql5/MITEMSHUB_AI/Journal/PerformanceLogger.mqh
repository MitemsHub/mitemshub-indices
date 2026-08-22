//+------------------------------------------------------------------+
//|                                      Journal/PerformanceLogger.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 PerformanceLogger.         |
//|                                                                  |
//|  Incremental run-level aggregation.  The Phase-7 ExecutionEngine |
//|  feeds one closed outcome at a time (return_r, pnl, hold_bars);  |
//|  the logger maintains the §18 headline metric set without        |
//|  re-scanning history: net/gross PnL, profit factor, expectancy,  |
//|  win rate, avg win/loss, max drawdown (from the cumulative-R     |
//|  curve), max consecutive win/loss streaks, avg hold.             |
//|                                                                  |
//|  Drawdown is tracked on the cumulative-R curve (peak-to-trough)  |
//|  so it is stake-independent and comparable across backtests —    |
//|  the same convention PerformanceAnalytics uses on OutcomeRecord[].|
//|                                                                  |
//|  A summary CSV row can be appended per run so the verify loop /  |
//|  external analysis can compare runs over time.                   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_JOURNAL_PERFORMANCELOGGER_MQH
#define MITEMSHUB_JOURNAL_PERFORMANCELOGGER_MQH

#include "../Core/Constants.mqh"

//--- The §18 headline set ------------------------------------------------------
struct PerformanceSummary
  {
   int    trades;
   int    wins;
   int    losses;
   double sum_r;            // total R (gross)
   double sum_pnl;          // total money PnL (0 if fed R-only)
   double gross_profit;     // sum of positive pnl (or +R when pnl==0)
   double gross_loss;       // abs sum of negative pnl (or -R when pnl==0)
   double profit_factor;    // gross_profit / gross_loss (0 when no losses)
   double win_rate;         // 0..1
   double avg_r;            // expectancy in R
   double avg_win_r;
   double avg_loss_r;
   double max_drawdown_r;   // peak-to-trough on cumulative R
   int    max_consec_wins;
   int    max_consec_losses;
   double avg_hold_bars;

   void Reset()
     {
      trades = wins = losses = 0;
      sum_r = sum_pnl = 0.0;
      gross_profit = gross_loss = 0.0;
      profit_factor = 0.0;
      win_rate = avg_r = avg_win_r = avg_loss_r = 0.0;
      max_drawdown_r = 0.0;
      max_consec_wins = max_consec_losses = 0;
      avg_hold_bars = 0.0;
     }
  };

class CPerformanceLogger
  {
private:
   PerformanceSummary m_s;
   double  m_cum_r;
   double  m_peak_r;
   int     m_streak;
   int     m_streak_sign;     // +1 winning streak, -1 losing streak, 0 none
   double  m_sum_hold;
   double  m_sum_win_r;       // winning return_r summed for avg_win_r
   double  m_sum_loss_r;      // losing return_r summed for avg_loss_r
   int     m_csv;

   void Recompute()
     {
      int n = m_s.trades;
      if(n == 0)
        {
         m_s.Reset();
         return;
        }
      m_s.win_rate  = (double)m_s.wins / (double)n;
      m_s.avg_r     = m_s.sum_r / (double)n;
      m_s.avg_win_r = (m_s.wins > 0) ? m_sum_win_r / (double)m_s.wins : 0.0;
      m_s.avg_loss_r= (m_s.losses > 0) ? m_sum_loss_r / (double)m_s.losses : 0.0;
      m_s.avg_hold_bars = m_s.trades > 0 ? m_sum_hold / (double)m_s.trades : 0.0;
      m_s.profit_factor = (m_s.gross_loss > 0.0)
                          ? m_s.gross_profit / m_s.gross_loss : 0.0;
     }

public:
   CPerformanceLogger()
     {
      m_csv = INVALID_HANDLE;
      Reset();
     }

   ~CPerformanceLogger()
     {
      CloseCSV();
     }

   void Reset()
     {
      m_s.Reset();
      m_cum_r = 0.0;
      m_peak_r = 0.0;
      m_streak = 0;
      m_streak_sign = 0;
      m_sum_hold = 0.0;
      m_sum_win_r = 0.0;
      m_sum_loss_r = 0.0;
     }

   //--- Feed one closed trade ---------------------------------------------------
   void AddOutcome(const double return_r, const double pnl,
                   const int hold_bars)
     {
      m_s.trades++;
      m_s.sum_r += return_r;
      m_s.sum_pnl += pnl;

      // gross profit/loss: money when tracked, R otherwise
      if(pnl > 0.0)
         m_s.gross_profit += pnl;
      else if(pnl < 0.0)
         m_s.gross_loss += -pnl;
      else if(return_r > 0.0)
         m_s.gross_profit += return_r;
      else if(return_r < 0.0)
         m_s.gross_loss += -return_r;

      if(return_r > 0.0)
        {
         m_s.wins++;
         m_sum_win_r += return_r;
        }
      else
        {
         m_s.losses++;
         m_sum_loss_r += return_r;
        }

      // consecutive streaks
      int sign = (return_r > 0.0) ? 1 : -1;
      if(sign == m_streak_sign)
         m_streak++;
      else
        {
         if(m_streak_sign > 0 && m_streak > m_s.max_consec_wins)
            m_s.max_consec_wins = m_streak;
         if(m_streak_sign < 0 && m_streak > m_s.max_consec_losses)
            m_s.max_consec_losses = m_streak;
         m_streak = 1;
         m_streak_sign = sign;
        }

      // drawdown on the cumulative-R curve
      m_cum_r += return_r;
      if(m_cum_r > m_peak_r)
         m_peak_r = m_cum_r;
      double dd = m_peak_r - m_cum_r;
      if(dd > m_s.max_drawdown_r)
         m_s.max_drawdown_r = dd;

      m_sum_hold += hold_bars;
      Recompute();
     }

   //--- outcome-record overload (pnl derived from a fixed stake; 0 = R-only) ----
   void AddOutcome(const OutcomeRecord &o, const double stake = 0.0)
     {
      AddOutcome(o.return_r, stake * o.return_r, o.hold_bars);
     }

   // MQL5 forbids reference return types - return the struct by value.
   PerformanceSummary Summary() const
     {
      return(m_s);
     }

   //--- flush the trailing streak into the summary (call before reading) --------
   void Finalize()
     {
      if(m_streak_sign > 0 && m_streak > m_s.max_consec_wins)
         m_s.max_consec_wins = m_streak;
      if(m_streak_sign < 0 && m_streak > m_s.max_consec_losses)
         m_s.max_consec_losses = m_streak;
      Recompute();
     }

   //--- optional summary CSV (one row per run) -----------------------------------
   bool OpenCSV(const string path)
     {
      if(m_csv != INVALID_HANDLE)
         CloseCSV();
      m_csv = FileOpen(path, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
      if(m_csv == INVALID_HANDLE)
         return(false);
      if(FileSize(m_csv) == 0)
        {
         FileSeek(m_csv, 0, SEEK_SET);
         FileWrite(m_csv, "trades,wins,losses,win_rate,sum_r,avg_r,gross_profit,"
                          "gross_loss,profit_factor,max_dd_r,max_consec_wins,"
                          "max_consec_losses,avg_hold_bars");
        }
      return(true);
     }

   void CloseCSV()
     {
      if(m_csv != INVALID_HANDLE)
        {
         FileFlush(m_csv);
         FileClose(m_csv);
         m_csv = INVALID_HANDLE;
        }
     }

   void WriteSummaryRow()
     {
      if(m_csv == INVALID_HANDLE)
         return;
      Finalize();
      FileSeek(m_csv, 0, SEEK_END);
      PerformanceSummary s = m_s;
      FileWrite(m_csv, s.trades, s.wins, s.losses, s.win_rate, s.sum_r, s.avg_r,
                s.gross_profit, s.gross_loss, s.profit_factor, s.max_drawdown_r,
                s.max_consec_wins, s.max_consec_losses, s.avg_hold_bars);
     }

   //--- plan §24 print ------------------------------------------------------------
   void PrintSummary(const string label)
     {
      PerformanceSummary s = m_s;
      Print(StringFormat("[PERF] %s: %d trades (%dW/%dL) hit=%.1f%% exp=%+.3fR "
                         "sumR=%+.2f PF=%.2f maxDD=%.2fR winStreak=%d lossStreak=%d",
                         label, s.trades, s.wins, s.losses, 100.0 * s.win_rate,
                         s.avg_r, s.sum_r, s.profit_factor, s.max_drawdown_r,
                         s.max_consec_wins, s.max_consec_losses));
     }
  };

#endif // MITEMSHUB_JOURNAL_PERFORMANCELOGGER_MQH
