//+------------------------------------------------------------------+
//|                                          Journal/TradeJournal.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 TradeJournal (CSV).        |
//|                                                                  |
//|  The plan's §33 machine-readable trade log: one CSV row per      |
//|  closed trade with every field the R-journal needs for external  |
//|  analysis.  Consumes the Phase-5 OutcomeRecord (the TradeQuality |
//|  Engine / Phase-7 ExecutionEngine already produce one per close) |
//|  plus the execution-time context the OutcomeRecord does not      |
//|  carry: symbol, volume, stake, confidence and composite score.   |
//|                                                                  |
//|  Columns (plan §33 + the close-time/hold extras analytics need): |
//|    opened_at,symbol,strategy,regime,direction,entry,sl,tp,       |
//|    volume,risk,pnl,confidence,score,exit,r,mae,mfe,exit_reason,  |
//|    closed_at,hold_bars                                           |
//|                                                                  |
//|  FILE FORMAT: FILE_TXT + hand-built CSV lines.  FILE_CSV's       |
//|  automatic quoting of delimiter-bearing strings behaves          |
//|  unpredictably in the Strategy Tester sandbox, so every row is   |
//|  composed explicitly (each field is a comma-free token; any      |
//|  external reason string is sanitized by CsvEscape).  This keeps  |
//|  the journal machine-parseable in the tester AND in production.  |
//|                                                                  |
//|  File semantics: open once (append), header on first create,     |
//|  FileSeek(SEEK_END) before every row.  In the Strategy Tester    |
//|  the file lives in the tester sandbox; in production it is the   |
//|  terminal's MQL5\Files directory.                                |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_JOURNAL_TRADEJOURNAL_MQH
#define MITEMSHUB_JOURNAL_TRADEJOURNAL_MQH

#include "../Core/Constants.mqh"

#define JOURNAL_CSV_HEADER \
   "opened_at,symbol,strategy,regime,direction,entry,sl,tp,volume,risk,pnl," \
   "confidence,score,exit,r,mae,mfe,exit_reason,closed_at,hold_bars"

class CTradeJournal
  {
private:
   int    m_handle;      // INVALID_HANDLE when not open
   string m_path;
   int    m_rows_written;

   bool EnsureHeader()
     {
      if(FileSize(m_handle) > 0)
         return(true);
      FileSeek(m_handle, 0, SEEK_SET);
      return(FileWriteString(m_handle, JOURNAL_CSV_HEADER + "\r\n") > 0);
     }

public:
   CTradeJournal()
     {
      m_handle       = INVALID_HANDLE;
      m_path         = "";
      m_rows_written = 0;
     }

   ~CTradeJournal()
     {
      Close();
     }

   //--- Open (or create) the CSV journal.  Returns false on failure. ----------
   bool Init(const string path)
     {
      if(m_handle != INVALID_HANDLE)
         Close();
      m_path = path;
      m_handle = FileOpen(path, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(m_handle == INVALID_HANDLE)
        {
         m_path = "";
         return(false);
        }
      bool ok = EnsureHeader();
      if(!ok)
        {
         FileClose(m_handle);
         m_handle = INVALID_HANDLE;
         return(false);
        }
      return(true);
     }

   bool IsOpen() const
     {
      return(m_handle != INVALID_HANDLE);
     }

   int RowsWritten() const
     {
      return(m_rows_written);
     }

   //--- Append one closed-trade row.  Returns false on write failure. ---------
   // stake 0.0 => pnl column is 0 (caller did not track the stake).
   bool Append(const OutcomeRecord &o, const string symbol,
               const double volume, const double stake,
               const double confidence, const double score)
     {
      if(m_handle == INVALID_HANDLE)
         return(false);
      FileSeek(m_handle, 0, SEEK_END);
      double pnl = stake * o.return_r;
      string line = StringFormat(
         "%I64d,%s,%s,%s,%s,%.5f,%.5f,%.5f,%.2f,%.5f,%.2f,%.2f,%.2f,"
         "%.5f,%.4f,%.4f,%.4f,%s,%I64d,%d\r\n",
         (long)o.opened_at, CsvEscape(symbol), StrategyToString(o.strategy),
         RegimeToString(o.regime), o.direction > 0 ? "BUY" : "SELL",
         o.entry, o.stop_loss, o.take_profit, volume, o.risk_distance, pnl,
         confidence, score, o.exit_price, o.return_r, o.mae_r, o.mfe_r,
         ExitReasonToString(o.exit_reason), (long)o.closed_at, o.hold_bars);
      if(FileWriteString(m_handle, line) > 0)
        {
         m_rows_written++;
         return(true);
        }
      return(false);
     }

   void Close()
     {
      if(m_handle != INVALID_HANDLE)
        {
         FileFlush(m_handle);
         FileClose(m_handle);
         m_handle = INVALID_HANDLE;
        }
     }

   //--- Static read-back helpers (tests + external analysis) -------------------
   // Returns true when the file exists and its first line is the header.
   static bool HasHeader(const string path)
     {
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return(false);
      string first = FileReadString(h);
      FileClose(h);
      return(StringFind(first, "opened_at") >= 0
             && StringFind(first, "exit_reason") >= 0);
     }

   //--- number of lines (header + data rows) -----------------------------------
   static ulong FileLineCount(const string path)
     {
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return(0);
      ulong n = 0;
      while(!FileIsEnding(h))
        {
         FileReadString(h);
         n++;
        }
      FileClose(h);
      return(n);
     }

   //--- split one data line into its fields (first 5 for read-back tests) ------
   static bool ReadFields(const string path, const int line_index,
                          string &fields[], int &field_count)
     {
      int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return(false);
      string target = "";
      for(int i = 0; i <= line_index && !FileIsEnding(h); i++)
         target = FileReadString(h);
      FileClose(h);
      if(target == "")
        {
         field_count = 0;
         return(false);
        }
      field_count = StringSplit(target, ',', fields);
      return(field_count > 0);
     }
  };

#endif // MITEMSHUB_JOURNAL_TRADEJOURNAL_MQH
