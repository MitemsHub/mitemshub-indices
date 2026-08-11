//+------------------------------------------------------------------+
//| Risk/RiskLimits.mqh                                              |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 RiskLimits.                |
//|                                                                  |
//|  The plan's Max* table with the account state needed to enforce  |
//|  it: equity / peak equity / day-start equity, realized session   |
//|  and daily PnL, consecutive-loss streak, per-day / per-hour      |
//|  trade counters, open-position count, and the EMERGENCY_STOP     |
//|  flag.  `AnyHardLimitBreached()` is the plan's TRADING DISABLED  |
//|  condition — no code path may auto-override a breached hard      |
//|  limit.                                                          |
//|                                                                  |
//|  Defaults come from Core/Constants.mqh (DEFAULT_MAX_*).  The     |
//|  consecutive-loss streak uses the Python RiskEngine's threshold  |
//|  (a scratch of -0.10R or better is NOT a loss — frictions alone  |
//|  must not trip the breaker), locked by the Phase-6 parity gate.  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_RISKLIMITS_MQH
#define MITEMSHUB_RISK_RISKLIMITS_MQH

#include "../Core/Constants.mqh"

//--- Python RiskEngine parity constants (risk/engine.py) ----------------------
#define PY_LOSS_R_THRESHOLD   -0.10   // material loss boundary for the streak

class CRiskLimits
  {
private:
   //--- limits (configurable; defaults from Constants.mqh) ----------
   double m_max_risk_per_trade_pct;   // per-trade risk cap (% of equity)
   double m_max_daily_loss_pct;       // net PnL loss from day start
   double m_max_daily_drawdown_pct;   // intraday peak-to-trough
   double m_max_equity_drawdown_pct;  // all-time peak-to-trough
   int    m_max_open_positions;
   double m_max_total_exposure_pct;   // % of equity in open exposure
   int    m_max_consecutive_losses;
   int    m_max_trades_per_hour;
   int    m_max_trades_per_day;
   bool   m_emergency_stop;

   //--- state ---------------------------------------------------------
   double m_equity;
   double m_peak_equity;
   double m_day_start_equity;
   double m_day_peak_equity;          // intraday peak for daily drawdown
   double m_realized_pnl;             // lifetime
   double m_day_realized_pnl;         // since day start
   int    m_consecutive_losses;
   int    m_trades_today;
   int    m_trades_this_hour;
   int    m_hour_bucket;              // for per-hour reset (epoch/3600)
   int    m_day_bucket;               // session-day (epoch/86400)
   int    m_open_positions;

public:
   CRiskLimits()
     {
      m_max_risk_per_trade_pct = DEFAULT_MAX_RISK_PER_TRADE_PCT / 100.0;
      m_max_daily_loss_pct     = DEFAULT_MAX_DAILY_LOSS_PCT / 100.0;
      m_max_daily_drawdown_pct = DEFAULT_MAX_DAILY_DRAWDOWN_PCT / 100.0;
      m_max_equity_drawdown_pct = DEFAULT_MAX_EQUITY_DRAWDOWN_PCT / 100.0;
      m_max_open_positions     = DEFAULT_MAX_OPEN_POSITIONS;
      m_max_total_exposure_pct = DEFAULT_MAX_TOTAL_EXPOSURE_PCT / 100.0;
      m_max_consecutive_losses = DEFAULT_MAX_CONSECUTIVE_LOSSES;
      m_max_trades_per_hour    = DEFAULT_MAX_TRADES_PER_HOUR;
      m_max_trades_per_day     = DEFAULT_MAX_TRADES_PER_DAY;
      m_emergency_stop         = false;
      m_equity = 0.0;
      m_peak_equity = 0.0;
      m_day_start_equity = 0.0;
      m_day_peak_equity = 0.0;
      m_realized_pnl = 0.0;
      m_day_realized_pnl = 0.0;
      m_consecutive_losses = 0;
      m_trades_today = 0;
      m_trades_this_hour = 0;
      m_hour_bucket = 0;
      m_day_bucket = 0;
      m_open_positions = 0;
     }

   //--- configuration -------------------------------------------------
   void SetMaxRiskPerTradePct(double v)    { m_max_risk_per_trade_pct = v; }
   void SetMaxDailyLossPct(double v)       { m_max_daily_loss_pct = v; }
   void SetMaxDailyDrawdownPct(double v)   { m_max_daily_drawdown_pct = v; }
   void SetMaxEquityDrawdownPct(double v)  { m_max_equity_drawdown_pct = v; }
   void SetMaxOpenPositions(int v)         { m_max_open_positions = v; }
   void SetMaxTotalExposurePct(double v)   { m_max_total_exposure_pct = v; }
   void SetMaxConsecutiveLosses(int v)     { m_max_consecutive_losses = v; }
   void SetMaxTradesPerHour(int v)         { m_max_trades_per_hour = v; }
   void SetMaxTradesPerDay(int v)          { m_max_trades_per_day = v; }

   double MaxRiskPerTradePct() const      { return(m_max_risk_per_trade_pct); }
   double MaxDailyLossPct() const         { return(m_max_daily_loss_pct); }
   double MaxDailyDrawdownPct() const     { return(m_max_daily_drawdown_pct); }
   double MaxEquityDrawdownPct() const    { return(m_max_equity_drawdown_pct); }
   int    MaxOpenPositions() const        { return(m_max_open_positions); }
   double MaxTotalExposurePct() const     { return(m_max_total_exposure_pct); }
   int    MaxConsecutiveLosses() const    { return(m_max_consecutive_losses); }
   int    MaxTradesPerHour() const        { return(m_max_trades_per_hour); }
   int    MaxTradesPerDay() const         { return(m_max_trades_per_day); }

   //--- account state -------------------------------------------------
   void SetEquity(const double equity, const datetime now_epoch)
     {
      m_equity = equity;
      if(m_equity > m_peak_equity)
         m_peak_equity = m_equity;
      if(m_equity > m_day_peak_equity)
         m_day_peak_equity = m_equity;
      SyncWindow((int)((long)now_epoch / 3600), (int)((long)now_epoch / 86400));
     }

   double Equity() const             { return(m_equity); }
   double PeakEquity() const         { return(m_peak_equity); }
   double DayStartEquity() const     { return(m_day_start_equity); }

   void EmergencyStop(const bool on) { m_emergency_stop = on; }
   bool EmergencyStopped() const     { return(m_emergency_stop); }

   int  OpenPositions() const        { return(m_open_positions); }
   int  ConsecutiveLosses() const    { return(m_consecutive_losses); }
   int  TradesToday() const          { return(m_trades_today); }
   int  TradesThisHour() const       { return(m_trades_this_hour); }

   //--- derived fractions (Python parity) ---------------------------------
   double DailyDrawdownFraction() const
     {
      double loss = MathMax(0.0, m_day_start_equity - m_equity);
      return(loss / MathMax(m_day_start_equity, 1e-9));
     }

   double EquityDrawdownFraction() const
     {
      double loss = MathMax(0.0, m_peak_equity - m_equity);
      return(loss / MathMax(m_peak_equity, 1e-9));
     }

   double DailyDrawdownFromPeakFraction() const
     {
      double loss = MathMax(0.0, m_day_peak_equity - m_equity);
      return(loss / MathMax(m_day_peak_equity, 1e-9));
     }

   //--- window rollover (session day / hour).  Returns true when the session
   //--- day rolled over (callers mirror the reset into DrawdownProtection).
   bool SyncWindow(const int hour_bucket, const int day_bucket)
     {
      bool day_rolled = false;
      if(m_day_bucket != day_bucket)
        {
         m_day_bucket = day_bucket;
         m_day_start_equity = m_equity;
         m_day_peak_equity = m_equity;
         m_day_realized_pnl = 0.0;
         m_consecutive_losses = 0;
         m_trades_today = 0;
         day_rolled = true;
        }
      if(m_hour_bucket != hour_bucket)
        {
         m_hour_bucket = hour_bucket;
         m_trades_this_hour = 0;
        }
      return(day_rolled);
     }

   void RegisterOpen()
     {
      m_open_positions++;
      m_trades_today++;
      m_trades_this_hour++;
     }

   void RegisterClose()
     {
      if(m_open_positions > 0)
         m_open_positions--;
     }

   //--- Python-parity outcome registration ---------------------------------
   // Python: equity += pnl; streak resets on a scratch (return_r >= -0.10)
   // and only material losses (return_r < -0.10) extend the streak.
   void RegisterOutcome(const double pnl, const double return_r)
     {
      if(m_open_positions > 0)
         m_open_positions--;
      m_realized_pnl += pnl;
      m_day_realized_pnl += pnl;
      m_equity += pnl;
      if(m_equity > m_peak_equity)
         m_peak_equity = m_equity;
      if(m_equity > m_day_peak_equity)
         m_day_peak_equity = m_equity;
      if(return_r < PY_LOSS_R_THRESHOLD)
         m_consecutive_losses++;
      else
         m_consecutive_losses = 0;
     }

   double RealizedPnl() const      { return(m_realized_pnl); }
   double DayRealizedPnl() const   { return(m_day_realized_pnl); }

   //--- the plan's TRADING DISABLED condition ------------------------------
   // Any hard limit breached -> true.  The caller (RiskEngine) must treat
   // this as absolute — no auto-override.
   bool AnyHardLimitBreached() const
     {
      if(m_emergency_stop)
         return(true);
      if(m_max_daily_loss_pct > 0.0 && DailyDrawdownFraction() >= m_max_daily_loss_pct)
         return(true);
      if(m_max_daily_drawdown_pct > 0.0
         && DailyDrawdownFromPeakFraction() >= m_max_daily_drawdown_pct)
         return(true);
      if(m_max_equity_drawdown_pct > 0.0
         && EquityDrawdownFraction() >= m_max_equity_drawdown_pct)
         return(true);
      if(m_max_consecutive_losses > 0
         && m_consecutive_losses >= m_max_consecutive_losses)
         return(true);
      if(m_max_trades_per_day > 0 && m_trades_today >= m_max_trades_per_day)
         return(true);
      if(m_max_trades_per_hour > 0 && m_trades_this_hour >= m_max_trades_per_hour)
         return(true);
      if(m_max_open_positions > 0 && m_open_positions >= m_max_open_positions)
         return(true);
      return(false);
     }
  };

#endif // MITEMSHUB_RISK_RISKLIMITS_MQH
