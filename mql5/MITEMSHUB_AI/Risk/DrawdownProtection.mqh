//+------------------------------------------------------------------+
//| Risk/DrawdownProtection.mqh                                      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 DrawdownProtection.        |
//|                                                                  |
//|  Dedicated drawdown monitor: all-time peak-equity drawdown,      |
//|  intraday peak-to-trough drawdown, and the daily-loss fraction   |
//|  (day-start equity vs current — the Python RiskEngine's          |
//|  daily_drawdown_fraction).  `Halted()` turns TRADING DISABLED    |
//|  on whenever any configured drawdown limit is breached — the     |
//|  hard-halt semantics of the plan: never automatically override a |
//|  breached safety stop.                                           |
//|                                                                  |
//|  All three fractions are computed the Python way (loss divided   |
//|  by the reference equity, floored at 1e-9 so a zero reference    |
//|  can never divide by zero).  The parity gate locks the math.     |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_DRAWDOWN_PROTECTION_MQH
#define MITEMSHUB_RISK_DRAWDOWN_PROTECTION_MQH

#include "../Core/Constants.mqh"

class CDrawdownProtection
  {
private:
   double m_equity;
   double m_peak_equity;
   double m_day_start_equity;
   double m_day_peak_equity;
   double m_max_equity_dd_pct;
   double m_max_daily_dd_pct;
   double m_max_daily_loss_pct;

public:
   CDrawdownProtection()
     {
      m_equity = 0.0;
      m_peak_equity = 0.0;
      m_day_start_equity = 0.0;
      m_day_peak_equity = 0.0;
      m_max_equity_dd_pct = DEFAULT_MAX_EQUITY_DRAWDOWN_PCT / 100.0;
      m_max_daily_dd_pct = DEFAULT_MAX_DAILY_DRAWDOWN_PCT / 100.0;
      m_max_daily_loss_pct = DEFAULT_MAX_DAILY_LOSS_PCT / 100.0;
     }

   void SetLimits(const double max_equity_dd_pct, const double max_daily_dd_pct,
                  const double max_daily_loss_pct)
     {
      m_max_equity_dd_pct = max_equity_dd_pct;
      m_max_daily_dd_pct = max_daily_dd_pct;
      m_max_daily_loss_pct = max_daily_loss_pct;
     }

   void SetEquity(const double equity)
     {
      m_equity = equity;
      if(m_equity > m_peak_equity)
         m_peak_equity = m_equity;
      if(m_equity > m_day_peak_equity)
         m_day_peak_equity = m_equity;
     }

   void OnNewSessionDay()
     {
      m_day_start_equity = m_equity;
      m_day_peak_equity = m_equity;
     }

   //--- Python-parity fractions --------------------------------------------
   double DailyLossFraction() const
     {
      double loss = MathMax(0.0, m_day_start_equity - m_equity);
      return(loss / MathMax(m_day_start_equity, 1e-9));
     }

   double EquityDrawdownFraction() const
     {
      double loss = MathMax(0.0, m_peak_equity - m_equity);
      return(loss / MathMax(m_peak_equity, 1e-9));
     }

   double DailyDrawdownFraction() const
     {
      double loss = MathMax(0.0, m_day_peak_equity - m_equity);
      return(loss / MathMax(m_day_peak_equity, 1e-9));
     }

   //--- the hard halt --------------------------------------------------------
   // Returns the FIRST breached limit's name ("" when healthy).  A non-empty
   // return means TRADING DISABLED and must never be auto-overridden.
   string Halted() const
     {
      if(m_max_daily_loss_pct > 0.0 && DailyLossFraction() >= m_max_daily_loss_pct)
         return("daily_loss_limit");
      if(m_max_daily_dd_pct > 0.0 && DailyDrawdownFraction() >= m_max_daily_dd_pct)
         return("daily_drawdown_limit");
      if(m_max_equity_dd_pct > 0.0 && EquityDrawdownFraction() >= m_max_equity_dd_pct)
         return("equity_drawdown_limit");
      return("");
     }
  };

#endif // MITEMSHUB_RISK_DRAWDOWN_PROTECTION_MQH
