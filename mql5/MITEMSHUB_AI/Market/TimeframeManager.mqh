//+------------------------------------------------------------------+
//|                                 Market/TimeframeManager.mqh      |
//|  MITEMSHUB AI MARKET ENGINE — configurable multi-timeframe map.  |
//|                                                                  |
//|  Defaults (from Constants): 4H macro / 1H directional / 15M      |
//|  setup / 5M confirmation / 1M execution — but every layer reads  |
//|  through this manager, so a different TF stack never touches     |
//|  strategy logic.  Also the single place that maps ENUM_TIMEFRAMES|
//|  ↔ seconds and validates the stack ordering.                    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_TIMEFRAMEMANAGER_MQH
#define MITEMSHUB_MARKET_TIMEFRAMEMANAGER_MQH

#include "../Core/Constants.mqh"

class CTimeframeManager
  {
private:
   ENUM_TIMEFRAMES m_macro;
   ENUM_TIMEFRAMES m_directional;
   ENUM_TIMEFRAMES m_setup;
   ENUM_TIMEFRAMES m_confirmation;
   ENUM_TIMEFRAMES m_execution;
   bool            m_valid;

public:
   CTimeframeManager()
     {
      m_macro        = DEFAULT_TF_MACRO;
      m_directional  = DEFAULT_TF_DIRECTIONAL;
      m_setup        = DEFAULT_TF_SETUP;
      m_confirmation = DEFAULT_TF_CONFIRMATION;
      m_execution    = DEFAULT_TF_EXECUTION;
      m_valid        = true;
     }

   //--- Validate + set the whole stack.  Ordering rule: macro >= directional
   //--- >= setup >= confirmation >= execution (by period seconds).
   bool SetTimeframes(const ENUM_TIMEFRAMES macro, const ENUM_TIMEFRAMES directional,
                      const ENUM_TIMEFRAMES setup, const ENUM_TIMEFRAMES confirmation,
                      const ENUM_TIMEFRAMES execution)
     {
      if(!IsValidTimeframe(macro) || !IsValidTimeframe(directional) ||
         !IsValidTimeframe(setup) || !IsValidTimeframe(confirmation) ||
         !IsValidTimeframe(execution))
        {
         m_valid = false;
         return(false);
        }
      long ms = SecondsOf(macro);
      long ds = SecondsOf(directional);
      long ss = SecondsOf(setup);
      long cs = SecondsOf(confirmation);
      long es = SecondsOf(execution);
      if(ms <= 0 || ds <= 0 || ss <= 0 || cs <= 0 || es <= 0 ||
         !(ms >= ds && ds >= ss && ss >= cs && cs >= es))
        {
         m_valid = false;
         return(false);
        }
      m_macro        = macro;
      m_directional  = directional;
      m_setup        = setup;
      m_confirmation = confirmation;
      m_execution    = execution;
      m_valid        = true;
      return(true);
     }

   //--- Only the timeframes the engine is allowed to use.
   static bool IsValidTimeframe(const ENUM_TIMEFRAMES tf)
     {
      switch(tf)
        {
         case PERIOD_M1:
         case PERIOD_M5:
         case PERIOD_M15:
         case PERIOD_M30:
         case PERIOD_H1:
         case PERIOD_H4:
         case PERIOD_D1:
         case PERIOD_W1:
         case PERIOD_MN1:
            return(true);
         default:
            return(false);
        }
     }

   //--- Period length in seconds (0 for anything we do not support).
   static long SecondsOf(const ENUM_TIMEFRAMES tf)
     {
      switch(tf)
        {
         case PERIOD_M1:  return(60);
         case PERIOD_M5:  return(300);
         case PERIOD_M15: return(900);
         case PERIOD_M30: return(1800);
         case PERIOD_H1:  return(3600);
         case PERIOD_H4:  return(14400);
         case PERIOD_D1:  return(86400);
         case PERIOD_W1:  return(604800);
         case PERIOD_MN1: return(2592000L);
         default:         return(0);
        }
     }

   //--- Period length in minutes.
   static long MinutesOf(const ENUM_TIMEFRAMES tf)
     {
      long s = SecondsOf(tf);
      return(s / 60);
     }

   //--- Accessors ------------------------------------------------------------
   ENUM_TIMEFRAMES Macro() const         { return(m_macro); }
   ENUM_TIMEFRAMES Directional() const   { return(m_directional); }
   ENUM_TIMEFRAMES Setup() const         { return(m_setup); }
   ENUM_TIMEFRAMES Confirmation() const  { return(m_confirmation); }
   ENUM_TIMEFRAMES Execution() const     { return(m_execution); }
   bool Valid() const                    { return(m_valid); }
  };

#endif // MITEMSHUB_MARKET_TIMEFRAMEMANAGER_MQH
