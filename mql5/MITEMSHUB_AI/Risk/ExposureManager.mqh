//+------------------------------------------------------------------+
//| Risk/ExposureManager.mqh                                         |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 ExposureManager.           |
//|                                                                  |
//|  Aggregate-exposure authority: knows the account's margin mode   |
//|  (ACCOUNT_MARGIN_MODE from the terminal) and enforces the        |
//|  exposure limits — max open positions, max total exposure as a   |
//|  fraction of equity, and the hedging-vs-netting position rules   |
//|  (netting forbids a second position of EITHER direction;         |
//|  hedging allows one position per direction).  The plan's gate:   |
//|  "netting mode forbids second position".                         |
//|                                                                  |
//|  The engine never assumes multiple independent positions are     |
//|  possible — it inspects the account mode at runtime.             |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_EXPOSURE_MANAGER_MQH
#define MITEMSHUB_RISK_EXPOSURE_MANAGER_MQH

#include "../Core/Constants.mqh"

class CExposureManager
  {
private:
   int    m_mode;              // ACCOUNT_MARGIN_MODE_* (0 = unknown/demo)
   int    m_open_positions;
   int    m_long_positions;
   int    m_short_positions;
   double m_total_volume;
   double m_open_margin;       // in account currency (0 = unknown)
   double m_equity;
   int    m_max_open_positions;
   double m_max_exposure_pct;

public:
   CExposureManager()
     {
      m_mode = (int)ACCOUNT_MARGIN_MODE;
      m_open_positions = 0;
      m_long_positions = 0;
      m_short_positions = 0;
      m_total_volume = 0.0;
      m_open_margin = 0.0;
      m_equity = 0.0;
      m_max_open_positions = DEFAULT_MAX_OPEN_POSITIONS;
      m_max_exposure_pct = DEFAULT_MAX_TOTAL_EXPOSURE_PCT / 100.0;
     }

   void SetLimits(const int max_open_positions, const double max_exposure_pct)
     {
      m_max_open_positions = max_open_positions;
      m_max_exposure_pct = max_exposure_pct;
     }

   //--- mode override: a live caller (or the tests) may supply the account
   //--- mode explicitly instead of reading ACCOUNT_MARGIN_MODE at runtime.
   void SetMode(const int mode) { m_mode = mode; }

   void SetAccountState(const double equity, const double open_margin,
                        const double total_volume)
     {
      m_equity = equity;
      m_open_margin = open_margin;
      m_total_volume = total_volume;
     }

   void RegisterOpen(const int direction)
     {
      m_open_positions++;
      if(direction > 0)
         m_long_positions++;
      else if(direction < 0)
         m_short_positions++;
     }

   void RegisterClose(const int direction)
     {
      if(m_open_positions > 0)
         m_open_positions--;
      if(direction > 0 && m_long_positions > 0)
         m_long_positions--;
      else if(direction < 0 && m_short_positions > 0)
         m_short_positions--;
     }

   int  Mode() const             { return(m_mode); }
   int  OpenPositions() const    { return(m_open_positions); }
   int  LongPositions() const    { return(m_long_positions); }
   int  ShortPositions() const   { return(m_short_positions); }
   double TotalVolume() const    { return(m_total_volume); }

   bool IsNetting() const
     {
      return(m_mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING);
     }

   //--- Exposure as a fraction of equity (0..1); 0 when unknown ------------
   double ExposureFraction() const
     {
      if(m_equity <= 0.0)
         return(0.0);
      return(MathMax(0.0, m_open_margin) / m_equity);
     }

   bool ExposureExceedsLimit() const
     {
      if(m_max_exposure_pct > 0.0 && ExposureFraction() >= m_max_exposure_pct)
         return(true);
      return(false);
     }

   //--- Can a new position in `direction` (+1/-1) open? ---------------------
   // Netting: one position total — a second of EITHER direction is vetoed.
   // Hedging: one position per direction.
   // Mode unknown: be conservative — one position total (like netting).
   bool CanOpen(const int direction) const
     {
      if(m_max_open_positions > 0 && m_open_positions >= m_max_open_positions)
         return(false);
      if(m_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
        {
         if(direction > 0)
            return(m_long_positions == 0);
         return(m_short_positions == 0);
        }
      // netting (or unknown mode): a second position is forbidden
      return(m_open_positions == 0);
     }

   //--- human-readable mode -------------------------------------------------
   string ModeName() const
     {
      if(m_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
         return("HEDGING");
      if(m_mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING)
         return("NETTING");
      if(m_mode == ACCOUNT_MARGIN_MODE_EXCHANGE)
         return("EXCHANGE");
      return("UNKNOWN");
     }
  };

#endif // MITEMSHUB_RISK_EXPOSURE_MANAGER_MQH
