//+------------------------------------------------------------------+
//|                                        Journal/DecisionLogger.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 DecisionLogger.            |
//|                                                                  |
//|  Records EVERY decision the engine makes — BUY / SELL / WAIT —   |
//|  with the full decision-layer context, so the journal can answer |
//|  the plan's core question: "WHY did the engine enter or stand    |
//|  aside?"  A WAIT is a valid decision and is logged like any      |
//|  other: reasons, regime, scores and the (absent) trade geometry. |
//|                                                                  |
//|  Keeps a fixed-cap ring buffer (testable headlessly) and can     |
//|  mirror the same decision stream to a CSV (machine analysis of   |
//|  skip patterns / verdict quality over time).  The debug-mode     |
//|  [DECISION] print block is the plan §24 diagnostic format.       |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_JOURNAL_DECISIONLOGGER_MQH
#define MITEMSHUB_JOURNAL_DECISIONLOGGER_MQH

#include "../Core/Constants.mqh"

#define DECISION_LOG_CAPACITY 256

//--- One logged decision ------------------------------------------------------
struct DecisionLogEntry
  {
   datetime          ts;
   ENUM_DECISION     decision;     // BUY / SELL / WAIT
   ENUM_STRATEGY     strategy;
   ENUM_REGIME       regime;
   ENUM_SIGNAL_STRENGTH verdict;   // ConfidenceEngine Gate output
   double            confidence;
   double            composite;    // ScoreBreakdown.composite (0..1)
   double            setup_quality;
   double            entry;
   double            stop_loss;
   double            take_profit;
   string            reasons;
  };

class CDecisionLogger
  {
private:
   DecisionLogEntry m_buf[DECISION_LOG_CAPACITY];
   int              m_head;        // next write slot
   int              m_count;       // entries in the ring
   int              m_total;       // decisions ever logged (incl. overwritten)
   int              m_csv;         // CSV handle (INVALID_HANDLE = off)
   int              m_buy, m_sell, m_wait;

   void InitEntry(DecisionLogEntry &e)
     {
      e.ts = 0;
      e.decision = DECISION_WAIT;
      e.strategy = STRATEGY_NONE;
      e.regime   = REGIME_UNKNOWN;
      e.verdict  = SIGNAL_WAIT;
      e.confidence = 0.0;
      e.composite  = 0.0;
      e.setup_quality = 0.0;
      e.entry = e.stop_loss = e.take_profit = 0.0;
      e.reasons = "";
     }

public:
   CDecisionLogger()
     {
      Reset();
     }

   ~CDecisionLogger()
     {
      CloseCSV();
     }

   void Reset()
     {
      m_head = 0;
      m_count = 0;
      m_total = 0;
      m_csv = INVALID_HANDLE;
      m_buy = m_sell = m_wait = 0;
      for(int i = 0; i < DECISION_LOG_CAPACITY; i++)
         InitEntry(m_buf[i]);
     }

   //--- optional CSV mirror (FILE_TXT + hand-built rows — deterministic in the
   //--- tester sandbox; see TradeJournal.mqh for the rationale) -----------------
   bool OpenCSV(const string path)
     {
      if(m_csv != INVALID_HANDLE)
         CloseCSV();
      m_csv = FileOpen(path, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(m_csv == INVALID_HANDLE)
         return(false);
      if(FileSize(m_csv) == 0)
        {
         FileSeek(m_csv, 0, SEEK_SET);
         FileWriteString(m_csv, "ts,decision,strategy,regime,verdict,confidence,"
                                "composite,setup_quality,entry,sl,tp,reasons\r\n");
        }
      return(true);
     }

   void CloseCSV()
     {
      if(m_csv != INVALID_HANDLE)
        {
         FileFlush(m_csv);
         FileClose(m_csv);
         m_csv = INVALID_HANDLE;
        }
     }

   //--- Log one decision -------------------------------------------------------
   void Log(const datetime ts, const ENUM_DECISION decision,
            const ENUM_STRATEGY strategy, const ENUM_REGIME regime,
            const ENUM_SIGNAL_STRENGTH verdict, const double confidence,
            const double composite, const double setup_quality,
            const double entry, const double stop_loss, const double take_profit,
            const string reasons)
     {
      int slot = m_head;
      // MQL5 forbids local reference variables - write through the array slot
      // (a fresh InitEntry first so overwritten slots carry no stale fields).
      InitEntry(m_buf[slot]);
      m_buf[slot].ts             = ts;
      m_buf[slot].decision       = decision;
      m_buf[slot].strategy       = strategy;
      m_buf[slot].regime         = regime;
      m_buf[slot].verdict        = verdict;
      m_buf[slot].confidence     = confidence;
      m_buf[slot].composite      = composite;
      m_buf[slot].setup_quality  = setup_quality;
      m_buf[slot].entry          = entry;
      m_buf[slot].stop_loss      = stop_loss;
      m_buf[slot].take_profit    = take_profit;
      m_buf[slot].reasons        = reasons;

      m_head = (m_head + 1) % DECISION_LOG_CAPACITY;
      if(m_count < DECISION_LOG_CAPACITY)
         m_count++;
      m_total++;

      if(decision == DECISION_BUY)       m_buy++;
      else if(decision == DECISION_SELL) m_sell++;
      else                               m_wait++;

      if(m_csv != INVALID_HANDLE)
        {
         FileSeek(m_csv, 0, SEEK_END);
         string row = StringFormat(
            "%I64d,%s,%s,%s,%s,%.2f,%.2f,%.2f,%.5f,%.5f,%.5f,%s\r\n",
            (long)ts, DecisionToString(decision), StrategyToString(strategy),
            RegimeToString(regime), SignalStrengthToString(verdict),
            confidence, composite, setup_quality, entry, stop_loss,
            take_profit, CsvEscape(reasons));
         FileWriteString(m_csv, row);
        }

      //--- plan §24 debug block ------------------------------------------------
      Print(StringFormat("[DECISION] %s %s %s conf=%.2f score=%.2f verdict=%s "
                         "entry=%.5f sl=%.5f tp=%.5f reasons=%s",
                         TimeToString(ts, TIME_DATE | TIME_SECONDS),
                         DecisionToString(decision),
                         RegimeToString(regime), confidence, composite,
                         SignalStrengthToString(verdict), entry, stop_loss,
                         take_profit, reasons));
     }

   //--- convenience: log from a Phase-5 candidate -----------------------------
   void LogCandidate(const datetime ts, const StrategyCandidate &cand,
                     const ScoreBreakdown &score,
                     const ENUM_SIGNAL_STRENGTH verdict)
     {
      Log(ts, cand.decision, cand.strategy, cand.required_regime, verdict,
          cand.confidence, score.composite, score.setup_score,
          cand.entry, cand.stop_loss, cand.take_profit, cand.reason_codes);
     }

   //--- accessors ---------------------------------------------------------------
   int  Count() const       { return(m_count); }
   int  Total() const       { return(m_total); }
   int  Buys() const        { return(m_buy); }
   int  Sells() const       { return(m_sell); }
   int  Waits() const       { return(m_wait); }
   int  RingHead() const    { return(m_head); }

   //--- newest entry (index 0 = oldest in ring order) ---------------------------
   bool Get(const int index, DecisionLogEntry &out) const
     {
      if(index < 0 || index >= m_count)
         return(false);
      int slot = (m_head - m_count + index + DECISION_LOG_CAPACITY)
                 % DECISION_LOG_CAPACITY;
      out = m_buf[slot];
      return(true);
     }

   //--- last logged decision (most recent) --------------------------------------
   bool Last(DecisionLogEntry &out) const
     {
      return(Get(m_count - 1, out));
     }
  };

#endif // MITEMSHUB_JOURNAL_DECISIONLOGGER_MQH
