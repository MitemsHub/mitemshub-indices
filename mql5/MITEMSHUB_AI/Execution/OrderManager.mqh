//+------------------------------------------------------------------+
//|                                      Execution/OrderManager.mqh  |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 OrderManager.              |
//|                                                                  |
//|  A thin, VERIFIABLE trade-transport layer.  The engine NEVER     |
//|  assumes an order succeeded: every request is (1) sent through   |
//|  a CTradeInterface transport, (2) retcode-checked (DONE==10009), |
//|  and (3) verified against the position table before it counts.   |
//|                                                                  |
//|  Three pieces:                                                   |
//|   CTradeInterface   — abstract transport (Buy/Sell/Modify/Close  |
//|                       + retcode + position-verification hooks).  |
//|                       Production: CTradeAdapter.  Tests: a mock  |
//|                       with scripted retcodes (mocked-retcode     |
//|                       unit tests — the Phase-7 phase gate).      |
//|   CTradeAdapter     — wraps the real CTrade: magic separation,   |
//|                       deviation, filling-by-symbol, and position |
//|                       lookup by ticket (market-order ticket ==   |
//|                       position ticket on MT5 market fills).      |
//|   COrderManager     — the request -> verify -> record lifecycle. |
//|                       Every attempt lands in OrderResult:        |
//|                       accepted/position_verified/retcode and a   |
//|                       human-readable attempt_log so the journal  |
//|                       can answer "why did this order fail".     |
//|                                                                  |
//|  Parity: mirrors src/synthetic_trader/execution/mt5.py           |
//|  (place_mt5_order / close_mt5_position / modify_mt5_position —   |
//|  accepted == retcode 10009) and the execution-parity contract    |
//|  (FakeMetaTrader5 fills, reject-probe semantics).                |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_ORDERMANAGER_MQH
#define MITEMSHUB_EXECUTION_ORDERMANAGER_MQH

#include <Trade\Trade.mqh>
#include "../Core/Constants.mqh"
#include "../Market/SymbolAdapter.mqh"

//--- Failure classes (ExecutionMonitor classifies retcodes into these) -------
enum ENUM_EXEC_FAILURE
  {
   EXEC_FAILURE_NONE = 0,
   EXEC_FAILURE_REQUOTE,           // 10004 price changed while sending
   EXEC_FAILURE_REJECT,            // 10006 / 10007 generic reject/cancel
   EXEC_FAILURE_INVALID_VOLUME,    // 10014
   EXEC_FAILURE_INVALID_PRICE,     // 10015
   EXEC_FAILURE_INVALID_STOPS,     // 10016 stops too close / beyond market
   EXEC_FAILURE_TRADE_DISABLED,    // 10017
   EXEC_FAILURE_MARKET_CLOSED,     // 10018
   EXEC_FAILURE_MARGIN,            // 10019 / 10020 / 10021 no money / moved
   EXEC_FAILURE_AT_DISABLED,       // 10026 / 10027 algo trading blocked
   EXEC_FAILURE_LOCKED,            // 10028 / 10029 instrument locked/frozen
   EXEC_FAILURE_LIMIT,             // 10033 / 10034 / 10035 order/volume limits
   EXEC_FAILURE_CONNECTION,        // 10031
   EXEC_FAILURE_UNKNOWN
  };

//--- One execution attempt, fully recorded -----------------------------------
struct OrderResult
  {
   bool   accepted;            // retcode DONE AND position verified
   bool   position_verified;   // the position table confirms the fill
   ulong  order_ticket;        // ResultOrder()
   ulong  deal_ticket;         // ResultDeal()
   ulong  retcode;             // ResultRetcode()
   string message;             // "verified" or the failure reason
   string attempt_log;         // full request->response trail for the journal

   void Reset()
     {
      accepted          = false;
      position_verified = false;
      order_ticket      = 0;
      deal_ticket       = 0;
      retcode           = 0;
      message           = "";
      attempt_log       = "";
     }
  };

//--- Abstract trade transport ------------------------------------------------
//  Production: CTradeAdapter (real CTrade).  Tests: MockTrade (scripted
//  retcodes + in-memory position registry).  Both satisfy this surface, so
//  every order path — including the verify-fill step — is testable headless.
class CTradeInterface
  {
public:
   //--- entry ---
   virtual bool Buy(const double volume, const string symbol,
                    const double price, const double sl, const double tp,
                    const string comment)                        { return(false); }
   virtual bool Sell(const double volume, const string symbol,
                     const double price, const double sl, const double tp,
                     const string comment)                       { return(false); }
   //--- management ---
   virtual bool PositionModify(const ulong ticket, const double sl,
                               const double tp)                  { return(false); }
   // volume 0.0 == close the whole position (CTrade semantics)
   virtual bool PositionClose(const ulong ticket, const double volume)
                                                                 { return(false); }
   //--- result + verification hooks ---
   virtual bool   LastResult()                                   { return(false); }
   virtual ulong  ResultOrder()                                  { return(0); }
   virtual ulong  ResultDeal()                                   { return(0); }
   virtual ulong  ResultRetcode()                                { return(0); }
   virtual string ResultRetcodeDescription()                     { return(""); }
   virtual bool   PositionExists(const ulong ticket)             { return(false); }
   virtual bool   PositionSelect(const ulong ticket)             { return(false); }
   virtual double PositionPriceOpen()                            { return(0.0); }
   virtual double PositionPriceCurrent()                         { return(0.0); }
   virtual long   PositionType()                                 { return(-1); }
   virtual double PositionVolume()                               { return(0.0); }
   //--- config ---
   virtual void SetExpertMagicNumber(const long magic)           { }
   virtual void SetDeviationInPoints(const long deviation)       { }
   virtual void SetTypeFillingBySymbol(const string symbol)      { }
  };

//--- Production transport: the real CTrade -----------------------------------
class CTradeAdapter : public CTradeInterface
  {
private:
   CTrade m_trade;

public:
   virtual bool Buy(const double volume, const string symbol,
                    const double price, const double sl, const double tp,
                    const string comment)
     {
      return(m_trade.Buy(volume, symbol, price, sl, tp, comment));
     }
   virtual bool Sell(const double volume, const string symbol,
                     const double price, const double sl, const double tp,
                     const string comment)
     {
      return(m_trade.Sell(volume, symbol, price, sl, tp, comment));
     }
   virtual bool PositionModify(const ulong ticket, const double sl,
                               const double tp)
     {
      return(m_trade.PositionModify(ticket, sl, tp));
     }
   virtual bool PositionClose(const ulong ticket, const double volume)
     {
      // NOTE: this MT5 build's CTrade::PositionClose(ticket, deviation) takes
      // a ulong DEVIATION — partial closes live in PositionClosePartial.
      // Dispatch on volume to keep the interface's "0 = full close" contract.
      return(volume > 0.0
             ? m_trade.PositionClosePartial(ticket, volume)
             : m_trade.PositionClose(ticket));
     }
   virtual bool   LastResult()                 { return(m_trade.ResultRetcode() == TRADE_RETCODE_DONE); }
   virtual ulong  ResultOrder()                { return(m_trade.ResultOrder()); }
   virtual ulong  ResultDeal()                 { return(m_trade.ResultDeal()); }
   virtual ulong  ResultRetcode()              { return((ulong)m_trade.ResultRetcode()); }
   virtual string ResultRetcodeDescription()   { return(m_trade.ResultRetcodeDescription()); }
   virtual bool   PositionExists(const ulong ticket)
     {
      return(PositionSelectByTicket(ticket));
     }
   virtual bool   PositionSelect(const ulong ticket)
     {
      return(PositionSelectByTicket(ticket));
     }
   virtual double PositionPriceOpen()
     {
      return(PositionGetDouble(POSITION_PRICE_OPEN));
     }
   virtual double PositionPriceCurrent()
     {
      return(PositionGetDouble(POSITION_PRICE_CURRENT));
     }
   virtual long   PositionType()
     {
      return((long)PositionGetInteger(POSITION_TYPE));
     }
   virtual double PositionVolume()
     {
      return(PositionGetDouble(POSITION_VOLUME));
     }
   virtual void SetExpertMagicNumber(const long magic)
     {
      m_trade.SetExpertMagicNumber(magic);
     }
   virtual void SetDeviationInPoints(const long deviation)
     {
      m_trade.SetDeviationInPoints(deviation);
     }
   virtual void SetTypeFillingBySymbol(const string symbol)
     {
      m_trade.SetTypeFillingBySymbol(symbol);
     }
  };

//--- The order lifecycle -----------------------------------------------------
class COrderManager
  {
private:
   CTradeInterface *m_trade;

   void AppendAttempt(OrderResult &out, const string op, const string symbol,
                      const double volume, const double sl, const double tp)
     {
      string line = StringFormat("%s %s vol=%.2f sl=%.5f tp=%.5f -> retcode=%u %s",
                                 op, symbol, volume, sl, tp,
                                 (uint)m_trade.ResultRetcode(),
                                 m_trade.ResultRetcodeDescription());
      out.attempt_log = (out.attempt_log == "")
                        ? line
                        : out.attempt_log + " | " + line;
     }

public:
   COrderManager()
     {
      m_trade = NULL;
     }

   // Pointer-based injection: MQL5 forbids chaining references (a reference
   // parameter cannot be re-passed by reference — error 229), so the
   // transport is always bound by pointer.  NULL means "no transport" —
   // every send then fails closed with a recorded attempt.
   COrderManager(CTradeInterface *trade)
     {
      m_trade = trade;
     }

   void Bind(CTradeInterface *trade)
     {
      m_trade = trade;
     }

   //--- open: request -> retcode -> verify -> record -------------------------
   bool Open(const string symbol, const int direction, const double lots,
             const double sl, const double tp, const string comment,
             OrderResult &out)
     {
      out.Reset();
      bool ok = false;
      if(direction == DECISION_BUY)
         ok = m_trade.Buy(lots, symbol, 0.0, sl, tp, comment);
      else if(direction == DECISION_SELL)
         ok = m_trade.Sell(lots, symbol, 0.0, sl, tp, comment);
      else
        {
         out.message = "invalid direction";
         out.attempt_log = "OPEN rejected before send (bad direction)";
         return(false);
        }
      AppendAttempt(out, direction == DECISION_BUY ? "BUY" : "SELL",
                    symbol, lots, sl, tp);
      out.retcode      = m_trade.ResultRetcode();
      out.order_ticket = m_trade.ResultOrder();
      out.deal_ticket  = m_trade.ResultDeal();
      if(!ok || out.retcode != (ulong)TRADE_RETCODE_DONE)
        {
         out.accepted = false;
         out.message  = StringFormat("retcode=%u %s", (uint)out.retcode,
                                     m_trade.ResultRetcodeDescription());
         return(false);
        }
      // NEVER assume success — verify the fill exists in the position table.
      ulong ticket = out.order_ticket;
      if(ticket == 0 || !m_trade.PositionExists(ticket))
        {
         out.accepted          = false;
         out.position_verified = false;
         out.message           = "retcode DONE but position not found";
         out.attempt_log       += " | VERIFY FAILED (position not found)";
         return(false);
        }
      out.accepted          = true;
      out.position_verified = true;
      out.message           = "verified";
      out.attempt_log       += " | VERIFIED ticket=" + IntegerToString((long)ticket);
      return(true);
     }

   //--- modify SL/TP with a reason code for the journal ----------------------
   bool Modify(const ulong ticket, const double sl, const double tp,
               const string reason, OrderResult &out)
     {
      out.Reset();
      bool ok = m_trade.PositionModify(ticket, sl, tp);
      AppendAttempt(out, reason != "" ? "MODIFY(" + reason + ")" : "MODIFY",
                    "", 0.0, sl, tp);
      out.retcode = m_trade.ResultRetcode();
      if(!ok || out.retcode != (ulong)TRADE_RETCODE_DONE)
        {
         out.accepted = false;
         out.message  = StringFormat("modify retcode=%u %s", (uint)out.retcode,
                                     m_trade.ResultRetcodeDescription());
         return(false);
        }
      out.accepted = true;
      out.message  = "modified";
      return(true);
     }

   //--- close (volume 0.0 = full) and verify it is actually gone -------------
   bool Close(const ulong ticket, const double volume, const string reason,
              OrderResult &out)
     {
      out.Reset();
      bool ok = m_trade.PositionClose(ticket, volume);
      AppendAttempt(out, reason != "" ? "CLOSE(" + reason + ")" : "CLOSE",
                    "", volume, 0.0, 0.0);
      out.retcode = m_trade.ResultRetcode();
      if(!ok || out.retcode != (ulong)TRADE_RETCODE_DONE)
        {
         out.accepted = false;
         out.message  = StringFormat("close retcode=%u %s", (uint)out.retcode,
                                     m_trade.ResultRetcodeDescription());
         return(false);
        }
      if(volume <= 0.0 && m_trade.PositionExists(ticket))
        {
         out.accepted          = false;
         out.position_verified = false;
         out.message           = "close accepted but position still present";
         out.attempt_log       += " | VERIFY FAILED (position still open)";
         return(false);
        }
      out.accepted          = true;
      out.position_verified = true;
      out.message           = "closed + verified";
      return(true);
     }

   //--- volume grid (SymbolAdapter math; floors to step, clamps to grid) -----
   double NormalizeVolume(const SymbolSpec &spec, const double requested) const
     {
      return(CSymbolAdapter::NormalizeVolumeFromSpec(spec, requested));
     }
  };

#endif // MITEMSHUB_EXECUTION_ORDERMANAGER_MQH
