//+------------------------------------------------------------------+
//|                                       Market/MarketData.mqh      |
//|  MITEMSHUB AI MARKET ENGINE — live market access wrapper.        |
//|                                                                  |
//|  Thin layer over SymbolInfo* / CopyRates for the ACTIVE symbol.  |
//|  Everything here is broker-independent (reads symbol properties  |
//|  through MT5).  Decisions consume CLOSED bars only: BarClosed()  |
//|  shift 0 is the last fully-formed bar, never the forming one.    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_MARKETDATA_MQH
#define MITEMSHUB_MARKET_MARKETDATA_MQH

#include "../Core/Constants.mqh"
#include "TimeframeManager.mqh"

class CMarketData
  {
private:
   string m_symbol;

public:
   CMarketData()
     {
      m_symbol = "";
     }

   bool Init(const string symbol)
     {
      if(symbol == "")
         return(false);
      m_symbol = symbol;
      return(true);
     }

   string Symbol() const                 { return(m_symbol); }

   //--- Live quotes ----------------------------------------------------------
   double Bid() const                    { return(SymbolInfoDouble(m_symbol, SYMBOL_BID)); }
   double Ask() const                    { return(SymbolInfoDouble(m_symbol, SYMBOL_ASK)); }
   double Point() const                  { return(SymbolInfoDouble(m_symbol, SYMBOL_POINT)); }

   double SpreadPoints() const
     {
      double point = Point();
      double bid = Bid();
      double ask = Ask();
      return(point > 0.0 && ask > bid ? (ask - bid) / point : 0.0);
     }

   bool PricesFresh(const int max_age_seconds = 10) const
     {
      MqlTick tick;
      if(!SymbolInfoTick(m_symbol, tick))
         return(false);
      if(tick.bid <= 0.0 || tick.ask <= 0.0 || tick.ask < tick.bid)
         return(false);
      return((TimeCurrent() - tick.time) <= max_age_seconds);
     }

   //--- CLOSED bars ----------------------------------------------------------
   // shift 0 = last closed bar, 1 = previous, ... (forming bar is skipped).
   bool BarClosed(const ENUM_TIMEFRAMES tf, const int shift, MqlRates &out) const
     {
      // start_pos counts from the current (forming) bar: forming=0, so the
      // last closed bar is at start_pos=1+shift.  CopyRates wants an array.
      MqlRates arr[1];
      if(CopyRates(m_symbol, tf, 1 + shift, 1, arr) != 1)
         return(false);
      out = arr[0];
      return(true);
     }

   bool LastClose(const ENUM_TIMEFRAMES tf, double &close) const
     {
      MqlRates r;
      if(!BarClosed(tf, 0, r))
         return(false);
      close = r.close;
      return(true);
     }

   //--- Volatility read (for spread-relative gates) --------------------------
   double ATRPoints(const int period = DEFAULT_ATR_PERIOD) const
     {
      double atr[1];
      int handle = iATR(m_symbol, PERIOD_CURRENT, period);
      if(handle == INVALID_HANDLE)
         return(0.0);
      int copied = CopyBuffer(handle, 0, 0, 1, atr);
      if(copied != 1)
         return(0.0);
      double point = Point();
      return(point > 0.0 ? atr[0] / point : 0.0);
     }
  };

#endif // MITEMSHUB_MARKET_MARKETDATA_MQH
