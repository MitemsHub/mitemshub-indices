//+------------------------------------------------------------------+
//|                                      Market/SymbolAdapter.mqh    |
//|  MITEMSHUB AI MARKET ENGINE — broker/symbol independence.        |
//|                                                                  |
//|  EVERY symbol-dependent quantity is discovered at init via       |
//|  SymbolInfo* and read from this adapter.  No hard-coded prices,  |
//|  digits, points, or lots anywhere else in the engine.            |
//|                                                                  |
//|  Reference specs probed live on Blueberry Markets (2026-08-11):  |
//|    SYN75 : digits=3 point=0.001 tick_size=0.001 tick_value=0.1   |
//|            vol 0.01..100 step 0.01, stops_level=0 freeze=0       |
//|            contract=100 calc_mode=CFD_INDEX, spread~1080 pts     |
//|            last ~1668.9/1669.9 (ask/bid)                         |
//|    SYN100: digits=3 point=0.001 tick_size=0.001 tick_value=0.1   |
//|            vol 0.01..100 step 0.01, stops_level=0 freeze=0       |
//|            contract=100 calc_mode=CFD_INDEX, spread~431 pts      |
//|            last ~353.8/354.3                                     |
//|  The adapter does NOT assume any of these — it measures.  The    |
//|  fixture block below is used by Tests/Phase1Tests.mq5 to verify  |
//|  the adapter against known-good values.                          |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_SYMBOLADAPTER_MQH
#define MITEMSHUB_MARKET_SYMBOLADAPTER_MQH

#include "../Core/Constants.mqh"

//--- Full snapshot of a symbol's tradable spec -------------------------------
struct SymbolSpec
  {
   string symbol;
   //--- price geometry ---
   double point;
   long   digits;             // SymbolInfoInteger writes into long&
   double tick_size;
   double tick_value;
   double contract_size;
   long   trade_calc_mode;
   long   trade_mode;
   //--- volume ---
   double volume_min;
   double volume_max;
   double volume_step;
   //--- execution ---
   long   stops_level;    // in points
   long   freeze_level;   // in points
   //--- live ---
   double bid;
   double ask;
   double spread_points;
   //--- validity ---
   bool   valid;
  };

class CSymbolAdapter
  {
private:
   SymbolSpec m_spec;
   string     m_error;

public:
   CSymbolAdapter()
     {
      m_spec.valid = false;
      m_error = "";
     }

   //--- Discover everything about the current symbol -------------------------
   bool Init(const string symbol)
     {
      m_spec.symbol = symbol;

      if(!SymbolInfoInteger(symbol, SYMBOL_DIGITS, m_spec.digits) ||
         !SymbolInfoDouble (symbol, SYMBOL_POINT, m_spec.point) ||
         !SymbolInfoDouble (symbol, SYMBOL_TRADE_TICK_SIZE, m_spec.tick_size) ||
         !SymbolInfoDouble (symbol, SYMBOL_TRADE_TICK_VALUE, m_spec.tick_value) ||
         !SymbolInfoDouble (symbol, SYMBOL_TRADE_CONTRACT_SIZE, m_spec.contract_size) ||
         !SymbolInfoDouble (symbol, SYMBOL_VOLUME_MIN, m_spec.volume_min) ||
         !SymbolInfoDouble (symbol, SYMBOL_VOLUME_MAX, m_spec.volume_max) ||
         !SymbolInfoDouble (symbol, SYMBOL_VOLUME_STEP, m_spec.volume_step) ||
         !SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL, m_spec.stops_level) ||
         !SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL, m_spec.freeze_level) ||
         !SymbolInfoInteger(symbol, SYMBOL_TRADE_CALC_MODE, m_spec.trade_calc_mode) ||
         !SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE, m_spec.trade_mode))
        {
         m_error = "SymbolInfo query failed for " + symbol;
         m_spec.valid = false;
         return(false);
        }

      MqlTick tick;
      if(SymbolInfoTick(symbol, tick))
        {
         m_spec.bid = tick.bid;
         m_spec.ask = tick.ask;
        }
      else
        {
         m_spec.bid = 0.0;
         m_spec.ask = 0.0;
        }
      m_spec.spread_points = (m_spec.point > 0.0 && m_spec.ask > m_spec.bid)
                             ? (m_spec.ask - m_spec.bid) / m_spec.point
                             : 0.0;

      m_spec.valid = (m_spec.point > 0.0) && (m_spec.digits >= 0) &&
                     (m_spec.tick_size > 0.0) && (m_spec.volume_min > 0.0) &&
                     (m_spec.volume_step > 0.0) && (m_spec.volume_max >= m_spec.volume_min);
      if(!m_spec.valid)
         m_error = "symbol spec invalid (point/volume/tick degenerate)";
      return(m_spec.valid);
     }

   //--- Accessors ------------------------------------------------------------
   // Note: MQL5 forbids pointer/reference return types — return a copy.
   SymbolSpec Spec() const                 { return(m_spec); }
   bool    Valid() const                   { return(m_spec.valid); }
   string  Error() const                   { return(m_error); }
   double  Point() const                   { return(m_spec.point); }
   int     Digits() const                  { return((int)m_spec.digits); }
   double  TickSize() const                { return(m_spec.tick_size); }
   double  TickValue() const               { return(m_spec.tick_value); }
   double  ContractSize() const            { return(m_spec.contract_size); }
   double  VolumeMin() const               { return(m_spec.volume_min); }
   double  VolumeMax() const               { return(m_spec.volume_max); }
   double  VolumeStep() const              { return(m_spec.volume_step); }
   int     StopsLevel() const              { return((int)m_spec.stops_level); }
   int     FreezeLevel() const             { return((int)m_spec.freeze_level); }
   double  Bid() const                     { return(m_spec.bid); }
   double  Ask() const                     { return(m_spec.ask); }
   double  SpreadPoints() const            { return(m_spec.spread_points); }
   int     CalcMode() const                { return((int)m_spec.trade_calc_mode); }
   int     TradeMode() const               { return((int)m_spec.trade_mode); }

   //--- Helpers --------------------------------------------------------------

   // Normalize a lot request to the symbol's min/max/step grid.
   double NormalizeVolume(const double requested) const
     {
      return(NormalizeVolumeFromSpec(m_spec, requested));
     }

   // Pure volume-grid math (testable without a live symbol).
   static double NormalizeVolumeFromSpec(const SymbolSpec &spec, const double requested)
     {
      double vmin  = spec.volume_min;
      double vmax  = spec.volume_max;
      double vstep = spec.volume_step;
      if(vmin <= 0.0)
         vmin = 0.01;
      if(vstep <= 0.0)
         vstep = 0.01;

      double vol = requested;
      if(vol < vmin)
         vol = vmin;
      if(vol > vmax)
         vol = vmax;
      vol = MathFloor(vol / vstep + 0.5) * vstep;
      if(vol < vmin)
         vol = vmin;
      return(vol);
     }

   // Points -> price distance (for this symbol's point size).
   double PointsToPrice(const double points) const
     {
      return(points * m_spec.point);
     }

   // Price distance -> points.
   double PriceToPoints(const double distance) const
     {
      return(m_spec.point > 0.0 ? distance / m_spec.point : 0.0);
     }

   // Round a price to the symbol's digits.
   double RoundPrice(const double price) const
     {
      double mult = MathPow(10, m_spec.digits);
      return(MathRound(price * mult) / mult);
     }

   // Validate a stop/target is beyond the broker's stops level (in points).
   bool IsStopAllowed(const double entry, const double stop) const
     {
      if(m_spec.stops_level <= 0)
         return(true);
      double dist = MathAbs(entry - stop) / m_spec.point;
      return(dist >= (double)m_spec.stops_level);
     }

   // True when the current spread (points) is at or below the given cap.
   bool SpreadWithin(const double max_points) const
     {
      return(max_points <= 0.0 || m_spec.spread_points <= max_points);
     }

   // True when prices are sane (bid>0, ask>=bid, not stale by > N seconds).
   bool PricesFresh(const int max_age_seconds = 10) const
     {
      MqlTick tick;
      if(!SymbolInfoTick(m_spec.symbol, tick))
         return(false);
      if(tick.bid <= 0.0 || tick.ask <= 0.0 || tick.ask < tick.bid)
         return(false);
      return((TimeCurrent() - tick.time) <= max_age_seconds);
     }

   //--- Fixture data for unit tests (values probed live on Blueberry) --------
   // The tests call FillFixture(SYN75) to get a known-good spec without
   // requiring the terminal; Init() is the live path.
   static void FillFixture(const string symbol, SymbolSpec &out)
     {
      out.symbol         = symbol;
      out.point          = 0.001;
      out.digits         = 3;
      out.tick_size      = 0.001;
      out.tick_value     = 0.1;
      out.contract_size  = 100.0;
      out.trade_calc_mode= 2;   // CFD_INDEX
      out.trade_mode     = 4;   // SYMBOL_TRADE_MODE_FULL
      out.volume_min     = 0.01;
      out.volume_max     = 100.0;
      out.volume_step    = 0.01;
      out.stops_level    = 0;
      out.freeze_level   = 0;
      if(symbol == "SYN100")
        {
         out.bid = 353.835;
         out.ask = 354.266;
         out.spread_points = (out.ask - out.bid) / out.point;   // ~431
        }
      else
        {
         out.bid = 1668.904;
         out.ask = 1669.984;
         out.spread_points = (out.ask - out.bid) / out.point;   // ~1080
        }
      out.valid = true;
     }
  };

#endif // MITEMSHUB_MARKET_SYMBOLADAPTER_MQH
