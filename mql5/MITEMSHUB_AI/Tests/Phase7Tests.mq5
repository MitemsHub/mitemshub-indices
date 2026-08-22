//+------------------------------------------------------------------+
//|                                       Tests/Phase7Tests.mq5      |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 unit tests.                |
//|                                                                  |
//|  Covers the Execution layer: OrderManager (request -> verify ->  |
//|  record with a CTradeInterface transport), StopManager and       |
//|  TakeProfitManager geometry guards, PositionManager (BE trail,   |
//|  time exit, partial close, closed-candle exits with reason       |
//|  codes), ExecutionMonitor retcode classification + backoff, and  |
//|  the ExecutionEngine orchestrator (never assumes success).       |
//|                                                                  |
//|  Mocked-retcode gate: MockTrade injects scripted retcodes and    |
//|  failure modes (DONE-without-position, close-without-removal)    |
//|  so the verify-fill path is tested headless — the same contract  |
//|  FakeMetaTrader5 exercises on the Python side.                   |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 7 unit tests — Execution"

#include "../Core/Constants.mqh"
#include "../Core/StateManager.mqh"
#include "../Market/SymbolAdapter.mqh"
#include "../Execution/OrderManager.mqh"
#include "../Execution/StopManager.mqh"
#include "../Execution/TakeProfitManager.mqh"
#include "../Execution/PositionManager.mqh"
#include "../Execution/ExecutionMonitor.mqh"
#include "../Execution/ExecutionEngine.mqh"

int g_pass = 0;
int g_fail = 0;

void Check(const string name, const bool ok, const string detail = "")
  {
   if(ok)
     {
      g_pass++;
      Print("[PHASE7] PASS  ", name);
     }
   else
     {
      g_fail++;
      Print("[PHASE7] FAIL  ", name, detail != "" ? "  -> " + detail : "");
     }
  }

bool CloseEnough(const double a, const double b, const double tol = 1e-9)
  {
   return(MathAbs(a - b) <= tol);
  }

//+------------------------------------------------------------------+
//| MockTrade — scripted-retcode CTradeInterface.                    |
//|  Fills create/remove positions in an in-memory registry; the     |
//|  verify-fill hooks (PositionExists / PositionSelect / price      |
//|  reads) answer from that registry, exactly like FakeMetaTrader5. |
//+------------------------------------------------------------------+
class MockTrade : public CTradeInterface
  {
private:
   struct MPos
     {
      ulong  ticket;
      int    type;          // 0 buy, 1 sell
      string symbol;
      double volume;
      double price_open;
      double price_current;
      bool   live;
     };
   MPos   m_pos[16];
   int    m_npos;
   ulong  m_next;
   ulong  m_rc_buy, m_rc_sell, m_rc_modify, m_rc_close;
   ulong  m_last_rc;
   ulong  m_last_order, m_last_deal;
   bool   m_accept_no_position;
   bool   m_close_keeps_position;
   long   m_magic;
   long   m_deviation;

public:
   MockTrade()
     {
      Reset();
     }

   void Reset()
     {
      m_npos = 0;
      m_next = 1000;
      m_rc_buy    = (ulong)TRADE_RETCODE_DONE;
      m_rc_sell   = (ulong)TRADE_RETCODE_DONE;
      m_rc_modify = (ulong)TRADE_RETCODE_DONE;
      m_rc_close  = (ulong)TRADE_RETCODE_DONE;
      m_last_rc   = 0;
      m_last_order = 0;
      m_last_deal  = 0;
      m_accept_no_position  = false;
      m_close_keeps_position = false;
      m_magic = 0;
      m_deviation = 0;
     }

   void SetRetcode(const string op, const ulong rc)
     {
      if(op == "buy")        m_rc_buy    = rc;
      else if(op == "sell")  m_rc_sell   = rc;
      else if(op == "modify")m_rc_modify = rc;
      else if(op == "close") m_rc_close  = rc;
     }
   void SetAcceptNoPosition(const bool v)   { m_accept_no_position = v; }
   void SetCloseKeepsPosition(const bool v) { m_close_keeps_position = v; }

   int Find(const ulong ticket) const
     {
      for(int i = 0; i < m_npos; i++)
         if(m_pos[i].ticket == ticket && m_pos[i].live)
            return(i);
      return(-1);
     }
   int CountOpen() const
     {
      int n = 0;
      for(int i = 0; i < m_npos; i++)
         if(m_pos[i].live)
            n++;
      return(n);
     }
   void SetPrice(const ulong ticket, const double price)
     {
      int i = Find(ticket);
      if(i >= 0)
         m_pos[i].price_current = price;
     }
   double VolumeOf(const ulong ticket) const
     {
      int i = Find(ticket);
      return(i >= 0 ? m_pos[i].volume : 0.0);
     }

   //--- interface -------------------------------------------------------------
   virtual bool Buy(const double volume, const string symbol,
                    const double price, const double sl, const double tp,
                    const string comment)
     {
      m_last_rc = m_rc_buy;
      if(m_rc_buy != (ulong)TRADE_RETCODE_DONE)
        {
         m_last_order = 0;
         m_last_deal  = 0;
         return(false);
        }
      if(m_accept_no_position)
        {
         m_last_order = 999;
         m_last_deal  = 999;
         return(true);
        }
      ulong t = m_next++;
      m_pos[m_npos].ticket         = t;
      m_pos[m_npos].type           = 0;
      m_pos[m_npos].symbol         = symbol;
      m_pos[m_npos].volume         = volume;
      m_pos[m_npos].price_open     = price > 0.0 ? price : 100.0;
      m_pos[m_npos].price_current  = m_pos[m_npos].price_open;
      m_pos[m_npos].live           = true;
      m_npos++;
      m_last_order = t;
      m_last_deal  = t;
      return(true);
     }

   virtual bool Sell(const double volume, const string symbol,
                     const double price, const double sl, const double tp,
                     const string comment)
     {
      m_last_rc = m_rc_sell;
      if(m_rc_sell != (ulong)TRADE_RETCODE_DONE)
        {
         m_last_order = 0;
         m_last_deal  = 0;
         return(false);
        }
      if(m_accept_no_position)
        {
         m_last_order = 999;
         m_last_deal  = 999;
         return(true);
        }
      ulong t = m_next++;
      m_pos[m_npos].ticket         = t;
      m_pos[m_npos].type           = 1;
      m_pos[m_npos].symbol         = symbol;
      m_pos[m_npos].volume         = volume;
      m_pos[m_npos].price_open     = price > 0.0 ? price : 100.0;
      m_pos[m_npos].price_current  = m_pos[m_npos].price_open;
      m_pos[m_npos].live           = true;
      m_npos++;
      m_last_order = t;
      m_last_deal  = t;
      return(true);
     }

   virtual bool PositionModify(const ulong ticket, const double sl,
                               const double tp)
     {
      m_last_rc = m_rc_modify;
      if(m_rc_modify != (ulong)TRADE_RETCODE_DONE)
         return(false);
      return(Find(ticket) >= 0);
     }

   virtual bool PositionClose(const ulong ticket, const double volume)
     {
      m_last_rc = m_rc_close;
      if(m_rc_close != (ulong)TRADE_RETCODE_DONE)
         return(false);
      int i = Find(ticket);
      if(i < 0)
         return(false);
      if(m_close_keeps_position)
         return(true);                       // accepted but position stays
      if(volume > 0.0 && m_pos[i].volume - volume > 1e-12)
        {
         m_pos[i].volume -= volume;          // partial close
         return(true);
        }
      m_pos[i].live = false;
      return(true);
     }

   virtual bool   LastResult()                 { return(m_last_rc == (ulong)TRADE_RETCODE_DONE); }
   virtual ulong  ResultOrder()                { return(m_last_order); }
   virtual ulong  ResultDeal()                 { return(m_last_deal); }
   virtual ulong  ResultRetcode()              { return(m_last_rc); }
   virtual string ResultRetcodeDescription()
     {
      return(StringFormat("rc%u", (uint)m_last_rc));
     }
   virtual bool   PositionExists(const ulong ticket)  { return(Find(ticket) >= 0); }
   virtual bool   PositionSelect(const ulong ticket)  { return(Find(ticket) >= 0); }
   virtual double PositionPriceOpen()
     {
      int i = Find(m_last_order);
      return(i >= 0 ? m_pos[i].price_open : 0.0);
     }
   virtual double PositionPriceCurrent()
     {
      int i = Find(m_last_order);
      return(i >= 0 ? m_pos[i].price_current : 0.0);
     }
   virtual long   PositionType()
     {
      int i = Find(m_last_order);
      return(i >= 0 ? (long)m_pos[i].type : -1);
     }
   virtual double PositionVolume()
     {
      int i = Find(m_last_order);
      return(i >= 0 ? m_pos[i].volume : 0.0);
     }
   virtual void SetExpertMagicNumber(const long magic)  { m_magic = magic; }
   virtual void SetDeviationInPoints(const long dev)    { m_deviation = dev; }
   virtual void SetTypeFillingBySymbol(const string symbol) { }
  };

//+------------------------------------------------------------------+
//| TestOrderManager — verify-fill lifecycle                         |
//+------------------------------------------------------------------+
void TestOrderManager()
  {
   Print("[PHASE7] --- OrderManager ---");
   MockTrade mock;
   COrderManager om(&mock);

   //--- happy path: buy verified ---------------------------------------------
   OrderResult r1;
   bool ok1 = om.Open("SYN75", DECISION_BUY, 0.5, 1665.5, 1674.0, "t", r1);
   Check("open buy accepted + verified", ok1 && r1.accepted && r1.position_verified);
   Check("open buy retcode DONE", r1.retcode == (ulong)TRADE_RETCODE_DONE);
   Check("open buy created 1 position", mock.CountOpen() == 1);
   Check("open buy verified ticket recorded", r1.order_ticket == 1000);

   //--- happy path: sell ------------------------------------------------------
   OrderResult r2;
   bool ok2 = om.Open("SYN75", DECISION_SELL, 0.3, 1670.5, 1662.0, "t", r2);
   Check("open sell accepted + verified", ok2 && r2.accepted && r2.position_verified);
   Check("open sell 2 positions total", mock.CountOpen() == 2);

   //--- rejection matrix (mocked retcodes) ------------------------------------
   ulong cases[6] = {(ulong)TRADE_RETCODE_INVALID_VOLUME,
                     (ulong)TRADE_RETCODE_INVALID_STOPS,
                     (ulong)TRADE_RETCODE_MARKET_CLOSED,
                     (ulong)TRADE_RETCODE_NO_MONEY,
                     (ulong)TRADE_RETCODE_SERVER_DISABLES_AT,
                     (ulong)TRADE_RETCODE_REQUOTE};
   for(int i = 0; i < 6; i++)
     {
      MockTrade m2;
      COrderManager om2(&m2);
      m2.SetRetcode("buy", cases[i]);
      OrderResult rr;
      om2.Open("SYN75", DECISION_BUY, 0.5, 1665.5, 1674.0, "t", rr);
      Check("reject rc" + IntegerToString((int)cases[i]) + " not accepted",
            !rr.accepted && !rr.position_verified);
      Check("reject rc" + IntegerToString((int)cases[i]) + " no position",
            m2.CountOpen() == 0);
     }
   // classification of the rejected buys
   MockTrade m3;      COrderManager om3(&m3);
   m3.SetRetcode("buy", (ulong)TRADE_RETCODE_INVALID_VOLUME);
   OrderResult rv;
   om3.Open("SYN75", DECISION_BUY, 0.5, 1665.5, 1674.0, "t", rv);
   Check("classify INVALID_VOLUME", CExecutionMonitor::Classify(rv.retcode) == EXEC_FAILURE_INVALID_VOLUME);
   Check("attempt log non-empty on rejection", rv.attempt_log != "");

   //--- DONE but no position (verify-fill failure) -----------------------------
   MockTrade m4;      COrderManager om4(&m4);
   m4.SetAcceptNoPosition(true);
   OrderResult r4;
   bool ok4 = om4.Open("SYN75", DECISION_BUY, 0.5, 1665.5, 1674.0, "t", r4);
   Check("DONE-without-position fails verification",
         !ok4 && !r4.accepted && !r4.position_verified);
   Check("verify failure names the cause",
         StringFind(r4.message, "position not found") >= 0);
   Check("verify failure logged", StringFind(r4.attempt_log, "VERIFY FAILED") >= 0);

   //--- modify ----------------------------------------------------------------
   OrderResult rm;
   bool okm = om.Modify(1000, 1666.0, 1674.0, "trail_arm", rm);
   Check("modify success", okm && rm.accepted && rm.retcode == (ulong)TRADE_RETCODE_DONE);
   Check("modify reason in log", StringFind(rm.attempt_log, "trail_arm") >= 0);
   MockTrade m5;      COrderManager om5(&m5);
   m5.SetRetcode("modify", (ulong)TRADE_RETCODE_INVALID_STOPS);
   OrderResult rm2;
   om5.Modify(1000, 1666.0, 1674.0, "trail_arm", rm2);
   Check("modify reject not accepted", !rm2.accepted);
   Check("modify reject classifies INVALID_STOPS",
         CExecutionMonitor::Classify(rm2.retcode) == EXEC_FAILURE_INVALID_STOPS);

   //--- close + verify gone ---------------------------------------------------
   OrderResult rc1;
   bool okc = om.Close(1000, 0.0, "STOP_HIT", rc1);
   Check("close success + verified", okc && rc1.accepted && rc1.position_verified);
   Check("close removed the position", mock.CountOpen() == 1);   // the sell stays
   MockTrade m6;      COrderManager om6(&m6);
   m6.SetCloseKeepsPosition(true);
   OrderResult rc2;
   bool okc2 = om6.Close(1000, 0.0, "STOP_HIT", rc2);
   Check("close DONE-but-stays fails verification",
         !okc2 && !rc2.accepted && !rc2.position_verified);

   //--- invalid direction never reaches the transport --------------------------
   // (1 open remains: the earlier close removed the buy, the sell stays)
   OrderResult rb;
   bool okb = om.Open("SYN75", DECISION_WAIT, 0.5, 1665.5, 1674.0, "t", rb);
   Check("WAIT direction rejected pre-send", !okb && mock.CountOpen() == 1);

   //--- volume grid ------------------------------------------------------------
   SymbolSpec spec;
   CSymbolAdapter::FillFixture("SYN75", spec);
   Check("vol 0.07 -> 0.07", CloseEnough(om.NormalizeVolume(spec, 0.07), 0.07));
   Check("vol 0.123 floors to 0.12", CloseEnough(om.NormalizeVolume(spec, 0.123), 0.12));
   Check("vol 150 clamps to 100", CloseEnough(om.NormalizeVolume(spec, 150.0), 100.0));
   Check("vol 0.001 floors to 0.01", CloseEnough(om.NormalizeVolume(spec, 0.001), 0.01));
  }

//+------------------------------------------------------------------+
//| TestStopManager / TestTakeProfitManager                          |
//+------------------------------------------------------------------+
void TestStopManager()
  {
   Print("[PHASE7] --- StopManager ---");
   Check("ATR stop long", CloseEnough(CStopManager::AtmStop(100.0, 1, 1.0, 2.0), 98.0));
   Check("ATR stop short", CloseEnough(CStopManager::AtmStop(100.0, -1, 1.0, 2.0), 102.0));
   Check("ATR stop degenerate atr=0", CloseEnough(CStopManager::AtmStop(100.0, 1, 0.0, 2.0), 0.0));
   Check("structure stop long", CloseEnough(CStopManager::StructureStop(100.0, 1, 1.0, 0.5), 99.5));
   Check("structure stop short", CloseEnough(CStopManager::StructureStop(100.0, -1, 1.0, 0.5), 100.5));
   Check("vol stop long frac 1%", CloseEnough(CStopManager::VolatilityStop(100.0, 1, 0.01), 99.0));
   Check("vol stop short frac 1%", CloseEnough(CStopManager::VolatilityStop(100.0, -1, 0.01), 101.0));
   Check("stops level 0 -> always allowed",
         CStopManager::MeetsStopsLevel(100.0, 99.97, 0.001, 0));
   Check("30 pts distance < 50 pt level -> blocked",
         !CStopManager::MeetsStopsLevel(100.0, 99.97, 0.001, 50));
   Check("60 pts distance >= 50 pt level -> allowed",
         CStopManager::MeetsStopsLevel(100.0, 99.94, 0.001, 50));
   Check("effective stop armed -> entry",
         CloseEnough(CStopManager::EffectiveStop(true, 100.0, 99.5), 100.0));
   Check("effective stop not armed -> original",
         CloseEnough(CStopManager::EffectiveStop(false, 100.0, 99.5), 99.5));
  }

void TestTakeProfitManager()
  {
   Print("[PHASE7] --- TakeProfitManager ---");
   Check("fixed-R long rr2", CloseEnough(CTakeProfitManager::FixedR(100.0, 99.5, 2.0), 101.0));
   Check("fixed-R short rr3", CloseEnough(CTakeProfitManager::FixedR(100.0, 100.5, 3.0), 98.5));
   Check("fixed-R degenerate risk 0", CloseEnough(CTakeProfitManager::FixedR(100.0, 100.0, 2.0), 0.0));
   Check("ATR target long", CloseEnough(CTakeProfitManager::AtrTarget(100.0, 1, 1.0, 0.8), 100.8));
   Check("min-RR rr2 vs 1.5 ok", CTakeProfitManager::MeetsMinRR(100.0, 99.5, 101.0, 1.5));
   Check("min-RR rr1 vs 2.0 blocked", !CTakeProfitManager::MeetsMinRR(100.0, 99.95, 100.05, 2.0));
   Check("min-RR degenerate risk 0 blocked", !CTakeProfitManager::MeetsMinRR(100.0, 100.0, 101.0, 2.0));
   Check("min-RR no gate -> non-degenerate ok", CTakeProfitManager::MeetsMinRR(100.0, 99.5, 101.0, 0.0));
  }

//+------------------------------------------------------------------+
//| TestPositionManager — management + reason codes                  |
//+------------------------------------------------------------------+
void TestPositionManager()
  {
   Print("[PHASE7] --- PositionManager ---");
   PositionMgmtConfig cfg;
   cfg.breakeven_trail = true;
   cfg.trail_frac      = 0.3;
   cfg.hold_sec        = 0;
   cfg.partial_close   = false;
   cfg.closed_candle_grace = true;

   //--- stop hit --------------------------------------------------------------
   CPositionManager pm;
   pm.Configure(cfg);
   pm.Open(1000, 1, 100.0, 99.5, 102.0, 0);
   ENUM_EXIT_REASON er; double ep; bool partial;
   bool exit1 = pm.UpdateBar(100.1, 99.4, 99.6, 300, 300, er, ep, partial);
   Check("stop exit triggered", exit1 && er == EXIT_STOP_HIT);
   Check("stop exit at stop price", CloseEnough(ep, 99.5));
   Check("stop exit reason code string", pm.ReasonCode() == "STOP_HIT");

   //--- breakeven trail --------------------------------------------------------
   CPositionManager pm2;
   pm2.Configure(cfg);
   pm2.Open(1001, 1, 100.0, 99.5, 102.0, 0);      // planned RR 4.0, arm at 1.2R
   // arming bar: MFE 1.6R but the low (100.1) stays ABOVE entry — the trail
   // arms without instantly stopping itself out (band same-bar semantics).
   bool hold1 = pm2.UpdateBar(100.8, 100.1, 100.5, 300, 300, er, ep, partial);
   Check("trail arms at MFE 1.6R >= 1.2R", !hold1 && pm2.TrailArmed());
   Check("trail reason recorded", pm2.ReasonCode() == "trail_armed_at_breakeven");
   bool exit2 = pm2.UpdateBar(100.2, 99.95, 100.0, 600, 300, er, ep, partial);
   Check("trail stop exit classifies BREAKEVEN_TRAIL",
         exit2 && er == EXIT_BREAKEVEN_TRAIL);
   Check("trail exit at entry", CloseEnough(ep, 100.0));

   //--- below threshold: no arm, plain stop ------------------------------------
   CPositionManager pm3;
   pm3.Configure(cfg);
   pm3.Open(1002, 1, 100.0, 99.5, 102.0, 0);
   bool hold2 = pm3.UpdateBar(100.4, 99.9, 100.2, 300, 300, er, ep, partial);
   Check("trail NOT armed below 1.2R threshold", !hold2 && !pm3.TrailArmed());
   bool exit3 = pm3.UpdateBar(100.1, 99.4, 99.6, 600, 300, er, ep, partial);
   Check("unarmed stop classifies STOP_HIT", exit3 && er == EXIT_STOP_HIT);

   //--- target hit (trail OFF — isolate pure stop/target semantics) ------------
   PositionMgmtConfig cfgNT = cfg;
   cfgNT.breakeven_trail = false;
   CPositionManager pm4;
   pm4.Configure(cfgNT);
   pm4.Open(1003, 1, 100.0, 99.5, 102.0, 0);
   bool exit4 = pm4.UpdateBar(102.1, 100.0, 102.0, 300, 300, er, ep, partial);
   Check("target exit triggered", exit4 && er == EXIT_TARGET_HIT);
   Check("target exit at target price", CloseEnough(ep, 102.0));

   //--- stop + target same bar: stop first (conservative) ----------------------
   CPositionManager pm5;
   pm5.Configure(cfgNT);
   pm5.Open(1004, 1, 100.0, 99.5, 102.0, 0);
   bool exit5 = pm5.UpdateBar(102.1, 99.4, 100.0, 300, 300, er, ep, partial);
   Check("stop+target same bar -> stop first", exit5 && er == EXIT_STOP_HIT);

   //--- time exit ---------------------------------------------------------------
   PositionMgmtConfig cfgT = cfg;
   cfgT.hold_sec = 3600;
   CPositionManager pm6;
   pm6.Configure(cfgT);
   pm6.Open(1005, 1, 100.0, 99.5, 102.0, 0);
   bool exit6 = pm6.UpdateBar(100.2, 99.9, 100.1, 3600, 300, er, ep, partial);
   Check("time exit triggers at hold expiry", exit6 && er == EXIT_TIME);
   Check("time exit at close", CloseEnough(ep, 100.1));
   Check("time exit reason string", pm6.ReasonCode() == "TIME_EXIT");

   //--- partial close at +1R ----------------------------------------------------
   PositionMgmtConfig cfgP = cfg;
   cfgP.partial_close = true;
   CPositionManager pm7;
   pm7.Configure(cfgP);
   pm7.Open(1006, 1, 100.0, 99.5, 102.0, 0);
   bool hold3 = pm7.UpdateBar(100.6, 99.9, 100.4, 300, 300, er, ep, partial);
   Check("partial signals at +1R", !hold3 && partial && pm7.PartialDone());
   Check("partial arms the trail", pm7.TrailArmed());
   Check("partial reason recorded", pm7.ReasonCode() == "partial_close_at_1r");
   bool exit7 = pm7.UpdateBar(100.2, 99.98, 100.0, 600, 300, er, ep, partial);
   Check("post-partial entry stop -> BREAKEVEN_TRAIL",
         exit7 && er == EXIT_BREAKEVEN_TRAIL);

   //--- MFE/MAE + realized R parity ---------------------------------------------
   CPositionManager pm8;
   pm8.Configure(cfg);
   pm8.Open(1007, 1, 100.0, 99.5, 102.0, 0);
   pm8.UpdateBar(100.9, 99.8, 100.3, 300, 300, er, ep, partial);
   Check("MFE_R 1.8", CloseEnough(pm8.MFE_R(), 1.8));
   Check("MAE_R 0.4", CloseEnough(pm8.MAE_R(), 0.4));
   Check("planned RR 4.0", CloseEnough(pm8.PlannedRR(), 4.0));
   pm8.UpdateBar(100.2, 99.95, 100.0, 600, 300, er, ep, partial);
   Check("realized R long at entry trail = 0.0",
         CloseEnough(pm8.RealizedR(ep), 0.0));
  }

//+------------------------------------------------------------------+
//| TestExecutionMonitor — retcode vocabulary + backoff              |
//+------------------------------------------------------------------+
void TestExecutionMonitor()
  {
   Print("[PHASE7] --- ExecutionMonitor ---");
   Check("DONE -> NONE", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_DONE) == EXEC_FAILURE_NONE);
   Check("INVALID_VOLUME", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_INVALID_VOLUME) == EXEC_FAILURE_INVALID_VOLUME);
   Check("INVALID_STOPS", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_INVALID_STOPS) == EXEC_FAILURE_INVALID_STOPS);
   Check("MARKET_CLOSED", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_MARKET_CLOSED) == EXEC_FAILURE_MARKET_CLOSED);
   Check("NO_MONEY -> MARGIN", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_NO_MONEY) == EXEC_FAILURE_MARGIN);
   Check("PRICE_OFF -> MARGIN", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_PRICE_OFF) == EXEC_FAILURE_MARGIN);
   Check("SERVER_DISABLES_AT -> AT_DISABLED", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_SERVER_DISABLES_AT) == EXEC_FAILURE_AT_DISABLED);
   Check("CLIENT_DISABLES_AT -> AT_DISABLED", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_CLIENT_DISABLES_AT) == EXEC_FAILURE_AT_DISABLED);
   Check("REQUOTE", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_REQUOTE) == EXEC_FAILURE_REQUOTE);
   Check("CONNECTION", CExecutionMonitor::Classify((ulong)TRADE_RETCODE_CONNECTION) == EXEC_FAILURE_CONNECTION);
   Check("backoff AT_DISABLED", CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_AT_DISABLED));
   Check("backoff MARGIN", CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_MARGIN));
   Check("backoff CONNECTION", CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_CONNECTION));
   Check("backoff REQUOTE", CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_REQUOTE));
   Check("no backoff INVALID_STOPS", !CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_INVALID_STOPS));
   Check("no backoff INVALID_VOLUME", !CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_INVALID_VOLUME));
   Check("no backoff NONE", !CExecutionMonitor::ShouldBackOff(EXEC_FAILURE_NONE));
  }

//+------------------------------------------------------------------+
//| TestExecutionEngine — orchestrator end-to-end                    |
//+------------------------------------------------------------------+
ExecutionConfig MakeExecCfg()
  {
   ExecutionConfig cfg;
   cfg.magic               = DEFAULT_MAGIC_NUMBER;
   cfg.max_slippage_points = 50;
   cfg.max_spread_points   = 2000.0;   // SYN75 fixture spread ~1080
   cfg.min_rr              = 2.0;
   cfg.live                = true;
   cfg.verify_fills        = true;
   return(cfg);
  }

StrategyCandidate MakeCand(const int decision, const double entry,
                           const double stop, const double target)
  {
   StrategyCandidate c;
   c.strategy          = STRATEGY_BAND;
   c.decision          = (ENUM_DECISION)decision;
   c.entry             = entry;
   c.stop_loss         = stop;
   c.take_profit       = target;
   c.setup_quality     = 0.9;
   c.confidence        = 0.9;
   c.required_regime   = REGIME_EXPANSION;
   c.reason_codes      = "band_test";
   c.signal_strength   = SIGNAL_STRONG_BUY;
   return(c);
  }

RiskVerdict MakeVerdict(const bool approved, const double lots)
  {
   RiskVerdict v;
   v.approved = approved;
   v.lots     = lots;
   v.stake    = lots > 0.0 ? 50.0 : 0.0;
   v.reasons  = approved ? "risk approved" : "vetoed";
   return(v);
  }

void TestExecutionEngine()
  {
   Print("[PHASE7] --- ExecutionEngine ---");
   SymbolSpec spec;
   CSymbolAdapter::FillFixture("SYN75", spec);   // bid 1668.904 ask 1669.984

   //--- happy path -------------------------------------------------------------
   MockTrade mock;
   ExecutionConfig cfg = MakeExecCfg();
   CExecutionEngine eng(&mock, cfg);
   CStateManager state;
   eng.SetStateManager(state);
   string log;
   bool ok = eng.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                         MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log);
   Check("engine open + verified", ok && eng.InPosition());
   Check("engine state tracks the ticket", state.OpenPositionTicket() != 0);
   Check("engine created 1 position", mock.CountOpen() == 1);
   Check("engine log trail non-empty", log != "");

   //--- spread guard ------------------------------------------------------------
   MockTrade m2;
   ExecutionConfig cfg2 = MakeExecCfg();
   cfg2.max_spread_points = 500.0;              // fixture ~1080 -> blocked
   CExecutionEngine eng2(&m2, cfg2);
   string log2;
   bool ok2 = eng2.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log2);
   Check("spread guard blocks", !ok2 && m2.CountOpen() == 0);
   Check("spread guard classified REQUOTE",
         eng2.LastFailure() == EXEC_FAILURE_REQUOTE);

   //--- hard halt ---------------------------------------------------------------
   MockTrade m3;
   CExecutionEngine eng3(&m3, MakeExecCfg());
   CStateManager s3;
   eng3.SetStateManager(s3);
   s3.SetHardHalt(true);
   string log3;
   bool ok3 = eng3.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log3);
   Check("hard halt blocks", !ok3 && m3.CountOpen() == 0);

   //--- WAIT decision ------------------------------------------------------------
   MockTrade m4;
   CExecutionEngine eng4(&m4, MakeExecCfg());
   string log4;
   bool ok4 = eng4.Execute(MakeCand(DECISION_WAIT, 1668.0, 1665.5, 1674.0),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log4);
   Check("WAIT never enters", !ok4 && m4.CountOpen() == 0);

   //--- price beyond stop ----------------------------------------------------------
   MockTrade m5;
   CExecutionEngine eng5(&m5, MakeExecCfg());
   string log5;
   bool ok5 = eng5.Execute(MakeCand(DECISION_BUY, 1668.0, 1670.0, 1674.0),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log5);
   Check("price below stop blocks", !ok5 && m5.CountOpen() == 0);
   Check("price-sanity classified INVALID_PRICE",
         eng5.LastFailure() == EXEC_FAILURE_INVALID_PRICE);

   //--- min-RR floor ---------------------------------------------------------------
   MockTrade m6;
   CExecutionEngine eng6(&m6, MakeExecCfg());
   string log6;
   bool ok6 = eng6.Execute(MakeCand(DECISION_BUY, 1668.0, 1667.95, 1668.05),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log6);
   Check("min-RR floor blocks (rr 1.0 < 2.0)", !ok6 && m6.CountOpen() == 0);

   //--- verify-fill failure ----------------------------------------------------------
   MockTrade m7;
   CExecutionEngine eng7(&m7, MakeExecCfg());
   m7.SetAcceptNoPosition(true);
   string log7;
   bool ok7 = eng7.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                           MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log7);
   Check("verify-fill failure rejected", !ok7 && !eng7.InPosition());
   Check("verify-fill failure classified",
         eng7.LastFailure() == EXEC_FAILURE_UNKNOWN
         || eng7.LastFailure() == EXEC_FAILURE_NONE);

   //--- ManageBar: stop exit through the engine -------------------------------------
   MockTrade m8;
   CExecutionEngine eng8(&m8, MakeExecCfg());
   CStateManager s8;
   eng8.SetStateManager(s8);
   string log8;
   eng8.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log8);
   OrderResult res8;
   bool partial8;
   double ep8;
   ENUM_EXIT_REASON er8 = eng8.ManageBar(1668.1, 1665.4, 1666.0, 300, 300,
                                         ep8, res8, partial8);
   Check("engine stop exit reason", er8 == EXIT_STOP_HIT && res8.accepted);
   Check("engine cleared position after exit", !eng8.InPosition()
         && m8.CountOpen() == 0 && s8.OpenPositionTicket() == 0);

   //--- ManageBar: target exit --------------------------------------------------------
   MockTrade m9;
   CExecutionEngine eng9(&m9, MakeExecCfg());
   string log9;
   eng9.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log9);
   OrderResult res9;
   bool partial9;
   double ep9;
   // the bar reaches the target WITHOUT dipping through entry (entry 1668),
   // so the trail arming on this bar cannot stop it out same-bar.
   ENUM_EXIT_REASON er9 = eng9.ManageBar(1674.1, 1668.5, 1674.0, 300, 300,
                                         ep9, res9, partial9);
   Check("engine target exit reason", er9 == EXIT_TARGET_HIT);
   Check("engine target exit at target", CloseEnough(ep9, 1674.0));

   //--- ManageBar: partial modifies stop, position stays -----------------------------
   MockTrade m10;
   CExecutionEngine eng10(&m10, MakeExecCfg());
   PositionMgmtConfig mgmt;
   mgmt.breakeven_trail = true;
   mgmt.trail_frac      = 0.3;
   mgmt.hold_sec        = 0;
   mgmt.partial_close   = true;
   mgmt.closed_candle_grace = true;
   eng10.ConfigureManagement(mgmt);
   string log10;
   eng10.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                 MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log10);
   OrderResult res10;
   bool partial10;
   double ep10;
   ENUM_EXIT_REASON er10 = eng10.ManageBar(1670.6, 1667.0, 1670.0, 300, 300,
                                           ep10, res10, partial10);
   Check("engine partial signal at +1R", partial10 && er10 == EXIT_NONE);
   Check("engine partial keeps position", eng10.InPosition());
   Check("engine partial modify accepted", res10.accepted);
   Check("engine partial armed the trail", eng10.PositionTrailArmed());

   //--- ManageBar: close accepted but position stays (verify-fail) -------------------
   MockTrade m11;
   CExecutionEngine eng11(&m11, MakeExecCfg());
   string log11;
   eng11.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                 MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log11);
   m11.SetCloseKeepsPosition(true);
   OrderResult res11;
   bool partial11;
   double ep11;
   ENUM_EXIT_REASON er11 = eng11.ManageBar(1668.1, 1665.4, 1666.0, 300, 300,
                                           ep11, res11, partial11);
   Check("engine close verify-fail surfaces", er11 == EXIT_STOP_HIT && !res11.accepted);

   //--- EmergencyFlat ----------------------------------------------------------------
   MockTrade m12;
   CExecutionEngine eng12(&m12, MakeExecCfg());
   CStateManager s12;
   eng12.SetStateManager(s12);
   string log12;
   eng12.Execute(MakeCand(DECISION_BUY, 1668.0, 1665.5, 1674.0),
                 MakeVerdict(true, 0.5), spec, spec.bid, spec.ask, log12);
   OrderResult res12;
   bool flat = eng12.EmergencyFlat(res12);
   Check("emergency flat closes + verifies", flat && res12.accepted);
   Check("emergency flat clears state", !eng12.InPosition()
         && s12.OpenPositionTicket() == 0 && m12.CountOpen() == 0);
  }

//+------------------------------------------------------------------+
//| Expert initialization — run the whole matrix then the verdict.   |
//+------------------------------------------------------------------+
int OnInit()
  {
   TestOrderManager();
   TestStopManager();
   TestTakeProfitManager();
   TestPositionManager();
   TestExecutionMonitor();
   TestExecutionEngine();
   Print(StringFormat("[PHASE7] === %d passed, %d failed ===", g_pass, g_fail));
   if(g_fail == 0)
      Print("[PHASE7] SUITE PASSED - Phase 7 complete");
   else
      Print("[PHASE7] SUITE FAILED - Phase 7 incomplete");
   return(INIT_SUCCEEDED);
  }

void OnTick() { }
