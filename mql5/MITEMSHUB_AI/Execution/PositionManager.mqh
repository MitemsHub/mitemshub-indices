//+------------------------------------------------------------------+
//|                                     Execution/PositionManager.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 PositionManager.           |
//|                                                                  |
//|  Stateful management of ONE open position, driven by CLOSED      |
//|  candles of the execution timeframe (no intraday-wick exits —    |
//|  the closed-candle grace: a stop trade-through on the forming    |
//|  bar never cancels a plan).  Supports, each with a reason code:  |
//|                                                                  |
//|   - breakeven trail  (arm at trail_frac x planned RR, move SL    |
//|                       to entry; hit => EXIT_BREAKEVEN_TRAIL)     |
//|   - time exit        (hold_sec expiry => EXIT_TIME at close)     |
//|   - partial close    (close half at +1R, move stop to entry;     |
//|                       reason code PARTIAL_AT_1R)                 |
//|   - stop / target    (EXIT_STOP_HIT / EXIT_TARGET_HIT; stop      |
//|                       wins on the same bar — conservative parity |
//|                       with the Python backtests)                 |
//|                                                                  |
//|  MFE/MAE and R tracking mirror the Phase-5 TradeQualityEngine    |
//|  (risk_distance = |entry - stop|; long R = (exit-entry)/risk).   |
//|  TrailArmed() is the exact CBandGeometry formula (mfe_r >= frac  |
//|  x planned_rr) — the band tester's parity.                       |
//|                                                                  |
//|  ARCHITECTURE:                                                   |
//|  This module is purely a TRACKER — it does not execute orders.   |
//|  The ExecutionEngine reads the UpdateBar() output and calls      |
//|  COrderManager to actually close/modify the position.            |
//|                                                                  |
//|  CLOSED-CANDLE DISCIPLINE:                                       |
//|  Every engine consumes CLOSED bars only; signals fire once per    |
//|  closed execution bar.  The forming bar never counts for exits.  |
//|  This ensures the EA and Python backtest see the same price data.|
//|                                                                  |
//|  EXIT PRIORITY (same-bar resolution):                            |
//|  1. STOP_HIT wins over TARGET_HIT (conservative parity)         |
//|  2. BREAKEVEN_TRAIL requires MFE >= trail_frac * planned_rr     |
//|  3. TIME exit fires at candle close after horizon expiry          |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_POSITIONMANAGER_MQH
#define MITEMSHUB_EXECUTION_POSITIONMANAGER_MQH

#include "../Core/Constants.mqh"

//+------------------------------------------------------------------+
//| POSITION MANAGEMENT CONFIGURATION                                  |
//|                                                                    |
//| Configuration struct for position management behavior.            |
//| These values come from Config.mqh inputs and are set once at      |
//| EA initialization.                                                |
//|                                                                    |
//| FIELDS:                                                           |
//|   breakeven_trail  - arm the trail and move SL to entry          |
//|   trail_frac       - arm when MFE >= frac x planned RR          |
//|   hold_sec         - time exit after this many seconds           |
//|   partial_close    - close half at +1R and move stop to entry   |
//|   closed_candle_grace - exits only on closed-candle trade-throughs|
//+------------------------------------------------------------------+
struct PositionMgmtConfig
  {
   bool   breakeven_trail;    // arm the trail and move SL to entry
   double trail_frac;         // arm when MFE >= frac x planned RR
   int    hold_sec;           // time exit after this many seconds (0 = off)
   bool   partial_close;      // close half at +1R and move stop to entry
   bool   closed_candle_grace;// exits only on closed-candle trade-throughs
  };

//+------------------------------------------------------------------+
//| CPositionManager                                                    |
//|                                                                    |
//| Stateful tracker for a single open position.  This class does NOT |
//| execute orders — it only TRACKS position state and determines     |
//| when exits should occur based on closed candle data.              |
//|                                                                    |
//| LIFECYCLE:                                                        |
//|   1. Configure() — set management parameters                     |
//|   2. Open() — track a new position after fill                    |
//|   3. UpdateBar() — evaluate one closed bar for exits             |
//|   4. CloseTrack() — reset when position closes                   |
//|                                                                    |
//| MFE/MAE TRACKING:                                                 |
//|   - MFE (Max Favorable Excursion): best unrealized profit        |
//|   - MAE (Max Adverse Excursion): worst unrealized loss           |
//|   - Both measured in PRICE units, converted to R via risk        |
//|   - R = (price - entry) / risk for longs                        |
//|   - R = (entry - price) / risk for shorts                       |
//|                                                                    |
//| BREAKEVEN TRAIL:                                                   |
//|   - Arms when MFE_R >= trail_frac * planned_rr                   |
//|   - Once armed, effective stop moves to entry                    |
//|   - Converts would-be -1R losses into ~0R exits                  |
//|   - Exact formula: TrailArmed(mfe_r, frac, planned_rr)          |
//+------------------------------------------------------------------+
class CPositionManager
  {
private:
   PositionMgmtConfig m_cfg;          // management configuration
   bool     m_in_pos;                 // true when tracking an open position
   long     m_ticket;                 // MT5 position ticket
   int      m_direction;              // +1 long, -1 short
   double   m_entry;                  // entry price
   double   m_stop;                   // original stop loss price
   double   m_target;                 // take profit price
   double   m_risk;                   // |entry - stop| in price units
   double   m_planned_rr;             // planned reward:risk ratio
   double   m_mfe;                    // max favorable excursion (price units)
   double   m_mae;                    // max adverse excursion (price units)
   bool     m_trail_armed;            // true when breakeven trail is active
   bool     m_partial_done;           // true when partial close at +1R done
   datetime m_opened_at;              // position open time
   string   m_last_reason;            // reason code of the last decision

   //+--------------------------------------------------------------+
   //| Set the last reason code for journal logging.                 |
   //| PARAM: reason - human-readable reason string                 |
   //+--------------------------------------------------------------+
   void SetReason(const string reason)   { m_last_reason = reason; }

public:
   //+--------------------------------------------------------------+
   //| Constructor — initialize with default config and no position. |
   //+--------------------------------------------------------------+
   CPositionManager()
     {
      ResetConfig();
      CloseTrack();
     }

   //+--------------------------------------------------------------+
   //| Reset configuration to default values.                        |
   //| Called by constructor and can be called to re-initialize.     |
   //+--------------------------------------------------------------+
   void ResetConfig()
     {
      m_cfg.breakeven_trail  = true;
      m_cfg.trail_frac       = DEFAULT_BAND_BREAKEVEN_TRAIL_FRAC;
      m_cfg.hold_sec         = DEFAULT_BAND_HOLD_SEC;
      m_cfg.partial_close    = false;
      m_cfg.closed_candle_grace = true;
     }

   //+--------------------------------------------------------------+
   //| Set management configuration.                                 |
   //| PARAM: cfg - configuration struct with management parameters |
   //+--------------------------------------------------------------+
   void Configure(const PositionMgmtConfig &cfg)   { m_cfg = cfg; }

   //+--------------------------------------------------------------+
   //| Get current management configuration.                         |
   //| RETURN: copy of current configuration                        |
   //+--------------------------------------------------------------+
   PositionMgmtConfig Config() const               { return(m_cfg); }

   //+--------------------------------------------------------------+
   //| Open tracking — call AFTER the fill is verified.              |
//|                                                                    |
//| Sets up all tracking variables for the new position.             |
//| The position must be confirmed open before calling this.          |
//|                                                                    |
//| PARAMS:                                                          |
//|   ticket    - MT5 position ticket                               |
//|   direction - +1 for long, -1 for short                         |
//|   entry     - fill price                                        |
//|   stop      - stop loss price                                   |
//|   target    - take profit price                                 |
//|   opened_at - position open time                                |
   //+--------------------------------------------------------------+
   void Open(const long ticket, const int direction, const double entry,
             const double stop, const double target, const datetime opened_at)
     {
      m_ticket      = ticket;
      m_direction   = direction > 0 ? 1 : -1;
      m_entry       = entry;
      m_stop        = stop;
      m_target      = target;
      m_risk        = MathAbs(entry - stop);
      if(m_risk <= 0.0)
         m_risk     = entry * 0.001;               // degenerate guard (parity)
      m_planned_rr  = (m_risk > 0.0) ? MathAbs(target - entry) / m_risk : 0.0;
      m_mfe         = 0.0;
      m_mae         = 0.0;
      m_trail_armed = false;
      m_partial_done= false;
      m_opened_at   = opened_at;
      m_in_pos      = true;
      SetReason("position_open");
     }

   //+--------------------------------------------------------------+
   //| Close tracking — reset all state when position closes.        |
//|                                                                    |
//| Must be called after a position is closed to reset the tracker. |
//| The tracker will be ready for a new position after this call.    |
   //+--------------------------------------------------------------+
   void CloseTrack()
     {
      m_in_pos  = false;
      m_ticket  = 0;
      m_direction = 0;
      m_entry = m_stop = m_target = m_risk = m_planned_rr = 0.0;
      m_mfe = m_mae = 0.0;
      m_trail_armed = false;
      m_partial_done= false;
      m_opened_at   = 0;
      SetReason("position_closed");
     }

   //+--------------------------------------------------------------+
   //| STATE ACCESSORS                                                |
   //|                                                                |
   //| Read-only accessors for position state.  All return const.    |
   //+--------------------------------------------------------------+
   bool   InPosition() const     { return(m_in_pos); }    // true when tracking open position
   long   Ticket() const         { return(m_ticket); }    // MT5 position ticket
   int    Direction() const      { return(m_direction); } // +1 long, -1 short
   double Entry() const          { return(m_entry); }     // entry price
   double Stop() const           { return(m_stop); }      // original stop loss
   double Target() const         { return(m_target); }    // take profit
   double Risk() const           { return(m_risk); }      // |entry - stop|
   double PlannedRR() const      { return(m_planned_rr); } // planned reward:risk

   //+--------------------------------------------------------------+
   //| Get MFE in R units (max favorable excursion).                 |
//| RETURN: MFE / risk (positive = favorable)                      |
   //+--------------------------------------------------------------+
   double MFE_R() const          { return(m_risk > 0.0 ? m_mfe / m_risk : 0.0); }

   //+--------------------------------------------------------------+
   //| Get MAE in R units (max adverse excursion).                   |
//| RETURN: MAE / risk (positive = adverse)                        |
   //+--------------------------------------------------------------+
   double MAE_R() const          { return(m_risk > 0.0 ? m_mae / m_risk : 0.0); }

   //+--------------------------------------------------------------+
   //| Check if breakeven trail is armed.                             |
//| RETURN: true when effective stop has moved to entry             |
   //+--------------------------------------------------------------+
   bool   TrailArmed() const     { return(m_trail_armed); }

   //+--------------------------------------------------------------+
   //| Check if partial close at +1R has been done.                  |
//| RETURN: true when partial close executed                       |
   //+--------------------------------------------------------------+
   bool   PartialDone() const    { return(m_partial_done); }

   //+--------------------------------------------------------------+
   //| Get position open time.                                        |
//| RETURN: datetime when position was opened                      |
   //+--------------------------------------------------------------+
   datetime OpenedAt() const     { return(m_opened_at); }

   //+--------------------------------------------------------------+
   //| Get the reason code of the last decision.                     |
//| RETURN: human-readable reason string                           |
   //+--------------------------------------------------------------+
   string ReasonCode() const     { return(m_last_reason); }

   //+--------------------------------------------------------------+
   //| THE BAND PARITY FORMULA (exact CBandGeometry::TrailArmed)     |
   //|                                                                |
   //| Determines if the breakeven trail should be armed.            |
   //| The trail arms when MFE in R units reaches the threshold:     |
   //|   mfe_r >= frac * planned_rr                                  |
   //|                                                                |
   //| For default frac=0.3 and a 4R trade:                         |
   //|   trail arms at MFE >= 1.2R                                   |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   mfe_r      - MFE in R units (positive = favorable)         |
   //|   frac       - fraction of planned RR to arm trail            |
   //|   planned_rr - planned reward:risk ratio                     |
   //| RETURN: true when trail should be armed                      |
   //+--------------------------------------------------------------+
   static bool TrailArmed(const double mfe_r, const double frac,
                          const double planned_rr)
     {
      return(frac > 0.0 && mfe_r >= frac * planned_rr);
     }

   //+--------------------------------------------------------------+
   //| Get the effective stop loss price.                             |
   //|                                                                |
   //| When the breakeven trail is armed, the effective stop is      |
   //| the entry price (breakeven).  Otherwise, it is the original   |
   //| stop loss.                                                     |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   trail_armed - true when breakeven trail is active           |
   //|   entry       - position entry price                         |
   //|   stop        - original stop loss price                     |
   //| RETURN: effective stop price (entry if trail armed, else stop)|
   //+--------------------------------------------------------------+
   static double EffectiveStop(const bool trail_armed, const double entry,
                               const double stop)
     {
      return(trail_armed ? entry : stop);
     }

   //+--------------------------------------------------------------+
   //| Evaluate one CLOSED bar of the execution timeframe.           |
   //|                                                                |
   //| This is the core method that determines position exits.       |
   //| It is called once per closed bar of the execution timeframe.  |
   //|                                                                |
   //| CLOSED-CANDLE DISCIPLINE:                                     |
   //|   - Only CLOSED bars are fed to this method                   |
   //|   - The forming bar never counts for exits                    |
   //|   - This ensures parity with the Python backtest              |
   //|                                                                |
   //| EXIT PRIORITY (same-bar resolution):                           |
   //|   1. STOP_HIT wins over TARGET_HIT (conservative parity)      |
   //|   2. BREAKEVEN_TRAIL requires MFE >= trail_frac * planned_rr  |
   //|   3. TIME exit fires at candle close after horizon expiry      |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   high            - bar high price                           |
   //|   low             - bar low price                            |
   //|   close           - bar close price                          |
   //|   bar_open_time   - bar open time                           |
   //|   bar_sec         - bar duration in seconds                  |
   //|   exit_reason_out - output: exit reason (ENUM_EXIT_REASON)   |
   //|   exit_price_out  - output: exit price                       |
   //|   partial_out     - output: true if partial close due        |
   //| RETURN: true when position should be exited                  |
   //+--------------------------------------------------------------+
   bool UpdateBar(const double high, const double low, const double close,
                  const datetime bar_open_time, const int bar_sec,
                  ENUM_EXIT_REASON &exit_reason_out, double &exit_price_out,
                  bool &partial_out)
     {
      exit_reason_out = EXIT_NONE;
      exit_price_out  = 0.0;
      partial_out     = false;
      if(!m_in_pos)
         return(false);

      //--- excursion update (MFE/MAE in price units) --------------------------
      if(m_direction > 0)
        {
         if(high - m_entry > m_mfe) m_mfe = high - m_entry;
         if(m_entry - low  > m_mae) m_mae = m_entry - low;
        }
      else
        {
         if(m_entry - low  > m_mfe) m_mfe = m_entry - low;
         if(high - m_entry > m_mae) m_mae = high - m_entry;
        }
      double mfe_r = MFE_R();

      //--- breakeven trail arming (one time) -----------------------------------
      if(m_cfg.breakeven_trail && !m_trail_armed &&
         TrailArmed(mfe_r, m_cfg.trail_frac, m_planned_rr))
        {
         m_trail_armed = true;
         SetReason("trail_armed_at_breakeven");
        }
      double eff_stop = EffectiveStop(m_trail_armed, m_entry, m_stop);

      //--- partial close at +1R (before exit checks — it is a management move)
      if(m_cfg.partial_close && !m_partial_done && mfe_r >= 1.0)
        {
         m_partial_done = true;
         m_trail_armed  = true;         // stop moves to entry with the half close
         partial_out    = true;
         SetReason("partial_close_at_1r");
         return(false);                 // position stays open
        }

      //--- exit checks (closed-candle trade-throughs only) ---------------------
      bool stop_hit   = (m_direction > 0) ? (low  <= eff_stop) : (high >= eff_stop);
      bool target_hit = (m_direction > 0) ? (high >= m_target) : (low  <= m_target);
      bool expired    = (m_cfg.hold_sec > 0)
                        && ((long)(bar_open_time + bar_sec) >=
                            (long)m_opened_at + m_cfg.hold_sec);

      if(stop_hit && target_hit)
        {
         exit_reason_out = m_trail_armed ? EXIT_BREAKEVEN_TRAIL : EXIT_STOP_HIT;
         exit_price_out  = eff_stop;                     // stop-first (conservative)
        }
      else if(stop_hit)
        {
         exit_reason_out = m_trail_armed ? EXIT_BREAKEVEN_TRAIL : EXIT_STOP_HIT;
         exit_price_out  = eff_stop;
        }
      else if(target_hit)
        {
         exit_reason_out = EXIT_TARGET_HIT;
         exit_price_out  = m_target;
        }
      else if(expired)
        {
         exit_reason_out = EXIT_TIME;
         exit_price_out  = close;
        }
      else
         return(false);                                  // hold

      SetReason(ExitReasonToString(exit_reason_out));
      return(true);
     }

   //+--------------------------------------------------------------+
   //| Calculate realized R for a closed position.                    |
   //|                                                                |
   //| R-multiple calculation (mirrors Phase-5 TradeQualityEngine):  |
   //|   risk_distance = |entry - stop|                              |
   //|   long R = (exit - entry) / risk_distance                    |
   //|   short R = (entry - exit) / risk_distance                   |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   exit_price - the price at which position was closed         |
   //| RETURN: realized R-multiple (positive = profit, negative = loss)|
   //+--------------------------------------------------------------+
   double RealizedR(const double exit_price) const
     {
      if(!m_in_pos || m_risk <= 0.0)
         return(0.0);
      return(m_direction > 0
             ? (exit_price - m_entry) / m_risk
             : (m_entry - exit_price) / m_risk);
     }
  };

#endif // MITEMSHUB_EXECUTION_POSITIONMANAGER_MQH
