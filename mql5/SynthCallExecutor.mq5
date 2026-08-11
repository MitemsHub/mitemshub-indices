//+------------------------------------------------------------------+
//|                                      SynthCallExecutor.mq5       |
//|  Executes Python-emitted approved calls inside the MT5 terminal. |
//|                                                                  |
//|  Architecture:  Python = quant research lab (EGARCH, band        |
//|  geometry, Stage-3 gate, walk-forward).  MQL5 = thin production  |
//|  executor: poll a small JSON call file, place the order with     |
//|  broker SL/TP, report state back.  No Python->MT5 IPC in the     |
//|  execution path, so execution is native tick-speed.              |
//|                                                                  |
//|  File protocol (MT5 Common Files folder, i.e.                    |
//|  %APPDATA%\MetaQuotes\Terminal\Common\Files):                    |
//|    IN:   synth_calls_<symbol>.json  (written atomically by       |
//|          synthetic_trader.execution.ea_emitter)                  |
//|    OUT:  synth_ea_state_<symbol>.json (this EA's exec state)     |
//|                                                                  |
//|  Safety:  proven-only gate (only evidence_status=proven calls    |
//|  execute), magic-number separation, max-spread guard, daily-     |
//|  loss halt, call expiry, call_id dedupe persisted across         |
//|  restarts.                                                       |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property link      ""
#property version   "1.00"
#property description "Executes Python-emitted band calls (proven-only)."

#include <Trade\Trade.mqh>

//--- inputs -----------------------------------------------------------------
input group "Call file"
input string InpCallFile        = "synth_calls_R_75.json"; // Call file name (Common\Files)
input string InpStateFile       = "synth_ea_state_R_75.json"; // State file written back
input int    InpPollSeconds     = 1;        // Poll interval (seconds)

input group "Execution"
input long   InpMagic           = 7788123;  // EA magic number (separates EA trades)
input bool   InpRequireProven   = true;     // Only execute evidence_status=proven
input double InpMaxSpreadPoints = 1500.0;   // Skip entry if spread above (points; 0=off)
                                       // NOTE: SYN75's NORMAL spread is ~1000-1100 points
                                       // (1.0-1.1 price units @ 0.001 point); 80 was a
                                       // hard blocker for every live entry.
input double InpMaxSlippagePoints = 50.0;   // Max deviation for market orders (points)
input double InpVolume          = 0.0;      // Fixed volume (0 = use call's volume)

input group "Risk management"
input double InpMaxDailyLossPct = 5.0;      // Halt new entries after this daily drawdown %
input bool   InpBreakevenTrail  = true;     // Move SL to entry at breakeven_frac of target
input double InpBreakevenFrac   = 0.30;     // MFE fraction of target that triggers BE move

//--- globals ----------------------------------------------------------------
CTrade  g_trade;
string  g_lastCallId   = "";
string  g_lastStatus   = "idle";
double  g_dayStartEquity = 0.0;
long    g_dayStartDay   = 0;
long    g_openTicket    = 0;double    g_mfe           = 0.0;   // max favorable excursion since entry (for BE trail)
double    g_entryPrice    = 0.0;
double    g_targetPrice   = 0.0;
bool      g_beMoved       = false;
datetime  g_backoffUntil  = 0;     // skip order attempts until this time (server AT block)

//+------------------------------------------------------------------+
//| JSON field extractor (flat schema, ASCII-safe).                  |
//| Returns the raw value string of "key" from a JSON object text.   |
//+------------------------------------------------------------------+
string JsonGetValue(const string text, const string key)
  {
   string needle = "\"" + key + "\":";
   int pos = StringFind(text, needle);
   if(pos < 0)
      return("");
   pos += StringLen(needle);
   int len = StringLen(text);
   // skip whitespace
   while(pos < len)
     {
      ushort c = StringGetCharacter(text, pos);
      if(c != ' ' && c != '\t' && c != '\n' && c != '\r')
         break;
      pos++;
     }
   if(pos >= len)
      return("");
   ushort first = StringGetCharacter(text, pos);
   if(first == '"')
     {
      // quoted string
      pos++;
      string out = "";
      for(int i = pos; i < len; i++)
        {
         ushort c = StringGetCharacter(text, i);
         if(c == '"')
            return(out);
         if(c == '\\')
           {
            i++;
            if(i < len)
               out += CharToString((uchar)StringGetCharacter(text, i));
            continue;
           }
         out += CharToString((uchar)c);
        }
      return(out);
     }
   // number / boolean / null — read until , or }
   int start = pos;
   while(pos < len)
     {
      ushort c = StringGetCharacter(text, pos);
      if(c == ',' || c == '}')
         break;
      pos++;
     }
   return(StringSubstr(text, start, pos - start));
  }

//+------------------------------------------------------------------+
//| Read a text file from Common\Files into a string.                |
//| Reads BINARY (FILE_BIN + FileReadArray) because FileReadString in |
//| TEXT mode stops at the first newline — the Python emitter writes  |
//| pretty-printed multi-line JSON, so a TXT read would truncate the  |
//| file to "{" and silently drop every call.                         |
//+------------------------------------------------------------------+
string ReadCommonFile(const string fname)
  {
   string path = fname;
   if(StringFind(fname, "\\") < 0)
      path = fname;
   int handle = FileOpen(path, FILE_READ | FILE_BIN | FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("SynthCallExecutor: cannot open call file ", fname, " (err ", GetLastError(), ")");
      return("");
     }
   string content = "";
   ulong size = FileSize(handle);
   if(size > 0)
     {
      char buf[];
      ArrayResize(buf, (int)size);
      int got = (int)FileReadArray(handle, buf, 0, (int)size);
      if(got > 0)
         content = CharArrayToString(buf, 0, got, CP_ACP);
     }
   FileClose(handle);
   return(content);
  }

//+------------------------------------------------------------------+
//| Write a text file to Common\Files (REWRITE truncates).           |
//+------------------------------------------------------------------+
bool WriteCommonFile(const string fname, const string content)
  {
   int handle = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_REWRITE);
   if(handle == INVALID_HANDLE)
     {
      Print("SynthCallExecutor: cannot open state file ", fname, " (err ", GetLastError(), ")");
      return(false);
     }
   bool ok = FileWriteString(handle, content);
   FileClose(handle);
   if(!ok)
      Print("SynthCallExecutor: failed writing ", fname, " (err ", GetLastError(), ")");
   return(ok);
  }

//+------------------------------------------------------------------+
//| Normalize volume to the symbol's min/max/step.                   |
//+------------------------------------------------------------------+
double NormalizeVolume(double vol)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(vmin <= 0.0)
      vmin = 0.01;
   if(vstep <= 0.0)
      vstep = 0.01;
   if(vol < vmin)
      vol = vmin;
   if(vol > vmax)
      vol = vmax;
   vol = MathFloor(vol / vstep + 0.5) * vstep;
   if(vol < vmin)
      vol = vmin;
   return(vol);
  }

//+------------------------------------------------------------------+
//| Persist the last processed call id + status to the state file.   |
//+------------------------------------------------------------------+
void SaveState(const string status, const string extra = "", const string callId = "")
  {
   string id = callId != "" ? callId : g_lastCallId;
   string json = "{";
   json += "\"call_id\":\"" + id + "\",";
   json += "\"status\":\"" + status + "\",";
   json += "\"updated_at_epoch\":" + IntegerToString((long)TimeCurrent()) + ",";
   json += "\"open_ticket\":" + IntegerToString(g_openTicket) + ",";
   json += "\"open_price\":" + DoubleToString(g_entryPrice, 5) + ",";
   json += "\"mfe\":" + DoubleToString(g_mfe, 5);
   if(extra != "")
      json += "," + extra;
   json += "}";
   WriteCommonFile(InpStateFile, json);
   g_lastStatus = status;
  }

//+------------------------------------------------------------------+
//| Check whether a position with our magic is already open.         |
//+------------------------------------------------------------------+
bool HasOpenPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      g_openTicket = (long)ticket;
      return(true);
     }
   g_openTicket = 0;
   return(false);
  }

//+------------------------------------------------------------------+
//| Daily-loss halt: freeze new entries after InpMaxDailyLossPct.    |
//+------------------------------------------------------------------+
bool DailyLossHalted()
  {
   long today = (long)(TimeCurrent() / 86400);
   if(g_dayStartDay != today)
     {
      g_dayStartDay  = today;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      return(false);
     }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double start  = g_dayStartEquity > 0.0 ? g_dayStartEquity : equity;
   double lossPct = start > 0.0 ? (start - equity) / start * 100.0 : 0.0;
   return(InpMaxDailyLossPct > 0.0 && lossPct >= InpMaxDailyLossPct);
  }

//+------------------------------------------------------------------+
//| Breakeven trail: once MFE reaches InpBreakevenFrac of the target |
//| distance, move SL to entry (one time).                           |
//+------------------------------------------------------------------+
void ManageBreakeven()
  {
   if(!InpBreakevenTrail || g_openTicket == 0 || g_beMoved)
      return;
   if(!PositionSelectByTicket((ulong)g_openTicket))
     {
      // position closed — clear tracking
      g_openTicket = 0;
      g_entryPrice = 0.0;
      g_targetPrice = 0.0;
      g_mfe = 0.0;
      g_beMoved = false;
      SaveState("closed");
      return;
     }
   double cur  = PositionGetDouble(POSITION_PRICE_CURRENT);
   double open = PositionGetDouble(POSITION_PRICE_OPEN);
   long   type = PositionGetInteger(POSITION_TYPE);
   if(type == POSITION_TYPE_BUY)
     {
      if(cur > g_mfe)
         g_mfe = cur;
      double targetDist = MathAbs(g_targetPrice - open);
      if(targetDist <= 0.0)
         return;
      double fracReached = (g_mfe - open) / targetDist;
      if(fracReached >= InpBreakevenFrac)
        {
         if(g_trade.PositionModify((ulong)g_openTicket, open, PositionGetDouble(POSITION_TP)))
           {
            g_beMoved = true;
            Print("SynthCallExecutor: breakeven trail applied @ ", DoubleToString(open, 5));
           }
        }
     }
   else if(type == POSITION_TYPE_SELL)
     {
      if(cur < g_mfe)
         g_mfe = cur;
      double targetDist = MathAbs(open - g_targetPrice);
      if(targetDist <= 0.0)
         return;
      double fracReached = (open - g_mfe) / targetDist;
      if(fracReached >= InpBreakevenFrac)
        {
         if(g_trade.PositionModify((ulong)g_openTicket, open, PositionGetDouble(POSITION_TP)))
           {
            g_beMoved = true;
            Print("SynthCallExecutor: breakeven trail applied @ ", DoubleToString(open, 5));
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Execute one call.  Returns true when the order was accepted.     |
//+------------------------------------------------------------------+
bool ExecuteCall(const string callId, const string direction,
                 const double entry, const double sl, const double tp,
                 const double volume)
  {
   double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   // spread guard
   if(InpMaxSpreadPoints > 0.0 && point > 0.0)
     {
      double spreadPts = (ask - bid) / point;
      if(spreadPts > InpMaxSpreadPoints)
        {
         Print("SynthCallExecutor: skip ", callId, " — spread ", DoubleToString(spreadPts, 1),
               " pts > ", DoubleToString(InpMaxSpreadPoints, 1));
         return(false);
        }
     }

   // sanity: never enter when price is already beyond the stop
   if(direction == "buy" && bid <= sl)
     {
      Print("SynthCallExecutor: skip ", callId, " — price below stop");
      return(false);
     }
   if(direction == "sell" && ask >= sl)
     {
      Print("SynthCallExecutor: skip ", callId, " — price above stop");
      return(false);
     }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints((int)InpMaxSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   bool ok = false;
   double vol = InpVolume > 0.0 ? NormalizeVolume(InpVolume) : NormalizeVolume(volume);
   if(direction == "buy")
      ok = g_trade.Buy(vol, _Symbol, 0.0, sl, tp, callId);
   else if(direction == "sell")
      ok = g_trade.Sell(vol, _Symbol, 0.0, sl, tp, callId);

   if(!ok)
     {
      Print("SynthCallExecutor: order failed for ", callId, " retcode=",
            IntegerToString(g_trade.ResultRetcode()), " ", g_trade.ResultRetcodeDescription());
      SaveState("rejected", "\"retcode\":" + IntegerToString(g_trade.ResultRetcode()), callId);
      // Server/client-side AT blocks (10026/10027) are account settings that
      // won't flip within a second — back off to once a minute so a 48h pass
      // doesn't flood the journal with ~86k rejected orders.  The call is NOT
      // marked processed, so the moment algo trading is enabled the order
      // still goes through.
      uint rc = g_trade.ResultRetcode();
      if(rc == 10026 || rc == 10027)
         g_backoffUntil = TimeCurrent() + 60;
      return(false);   // transient failure — caller retries next poll until expiry
     }

   // Locate the opened position by magic rather than trusting ResultOrder:
   // for a market order the position ticket can differ from the order ticket.
   if(!HasOpenPosition())
     {
      Print("SynthCallExecutor: order accepted but position not found for ", callId);
      SaveState("rejected", "\"retcode\":0,\"reason\":\"position_not_found\"", callId);
      return(false);
     }
   double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
   if(openPrice > 0.0)
      g_entryPrice = openPrice;
   else
      g_entryPrice = (direction == "sell" && bid > 0.0) ? bid : ask;
   g_targetPrice = tp;
   g_mfe = g_entryPrice;
   g_beMoved = false;
   SaveState("executed", "\"direction\":\"" + direction + "\",\"entry\":"
             + DoubleToString(entry, 5) + ",\"sl\":" + DoubleToString(sl, 5)
             + ",\"tp\":" + DoubleToString(tp, 5), callId);
   Print("SynthCallExecutor: executed ", callId, " ", direction, " vol=", DoubleToString(vol, 2),
         " ticket=", g_openTicket, " fill=", DoubleToString(g_entryPrice, 5));
   return(true);
  }

//+------------------------------------------------------------------+
//| Poll the call file and process a new call.                       |
//+------------------------------------------------------------------+
void ProcessCalls()
  {
   if(TimeCurrent() < g_backoffUntil)
      return;   // backing off a server-side AT block (see ExecuteCall)
   string content = ReadCommonFile(InpCallFile);
   if(content == "")
      return;

   string callId = JsonGetValue(content, "call_id");
   if(callId == "" || callId == g_lastCallId)
      return;   // dedupe — already processed

   // expiry check (0 = no expiry)
   long expiry = (long)StringToDouble(JsonGetValue(content, "expiry_epoch"));
   if(expiry > 0 && TimeCurrent() > expiry)
     {
      g_lastCallId = callId;
      SaveState("expired");
      Print("SynthCallExecutor: call ", callId, " expired");
      return;
     }

   // proven-only gate
   if(InpRequireProven)
     {
      string evidence = JsonGetValue(content, "evidence_status");
      if(evidence != "proven")
        {
         g_lastCallId = callId;
         SaveState("held_back", "\"reason\":\"evidence_status=" + evidence + "\"");
         Print("SynthCallExecutor: held back ", callId, " — evidence_status=", evidence);
         return;
        }
     }

   // venue symbol must match the chart the EA is attached to
   string venue = JsonGetValue(content, "venue_symbol");
   if(venue != "" && StringCompare(venue, _Symbol, false) != 0)
      return;   // wrong chart — not our call (do not mark processed)

   string direction = JsonGetValue(content, "direction");
   if(direction != "buy" && direction != "sell")
     {
      g_lastCallId = callId;
      SaveState("held_back", "\"reason\":\"bad_direction\"");
      return;
     }

   double entry = StringToDouble(JsonGetValue(content, "entry"));
   double sl    = StringToDouble(JsonGetValue(content, "stop_loss"));
   double tp    = StringToDouble(JsonGetValue(content, "take_profit"));
   double volume = StringToDouble(JsonGetValue(content, "volume"));
   if(entry <= 0.0 || sl <= 0.0 || tp <= 0.0 || volume <= 0.0)
     {
      g_lastCallId = callId;
      SaveState("held_back", "\"reason\":\"bad_levels\"");
      Print("SynthCallExecutor: held back ", callId, " — bad levels");
      return;
     }

   // one position at a time (strategy is single-position)
   if(HasOpenPosition())
     {
      Print("SynthCallExecutor: position already open (ticket ", g_openTicket, ") — skipping ", callId);
      return;   // do NOT mark processed — retry next poll until position closes
     }

   if(DailyLossHalted())
     {
      Print("SynthCallExecutor: daily loss halt active — skipping ", callId);
      return;
     }

   if(ExecuteCall(callId, direction, entry, sl, tp, volume))
      g_lastCallId = callId;   // mark processed only on acceptance
  }

//+------------------------------------------------------------------+
//| Expert Advisor event handlers                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_trade.SetExpertMagicNumber(InpMagic);
   if(EventSetTimer(InpPollSeconds) == false)
     {
      Print("SynthCallExecutor: EventSetTimer failed");
      return(INIT_FAILED);
     }
   // seed daily-loss baseline
   g_dayStartDay    = (long)(TimeCurrent() / 86400);
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   // Recover the last FILLED call id from the state file so restarts don't
   // re-fire an already-executed call.  A rejected/held-back call must NOT be
   // remembered — otherwise a restart silently skips a still-valid call and
   // the forward pass stalls forever (observed in the field).
   string state = ReadCommonFile(InpStateFile);
   if(state != "")
     {
      string prev = JsonGetValue(state, "call_id");
      string prevStatus = JsonGetValue(state, "status");
      if(prev != "" && (prevStatus == "executed" || prevStatus == "closed"))
         g_lastCallId = prev;
     }
   Print("SynthCallExecutor: initialized on ", _Symbol,
         " magic=", InpMagic, " proven_only=", InpRequireProven ? "true" : "false");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
   // Position management runs at tick speed (breakeven trail, tracking).
   ManageBreakeven();
  }

void OnTimer()
  {
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      return;
   ProcessCalls();
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }
//+------------------------------------------------------------------+
