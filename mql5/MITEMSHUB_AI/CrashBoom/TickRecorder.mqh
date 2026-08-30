//+------------------------------------------------------------------+
//|                                    CrashBoom/TickRecorder.mqh    |
//|  MITEMSHUB AI — ALWAYS-ON TICK RECORDER (v25.1)                  |
//|                                                                  |
//|  Persists every Boom/Crash tick to disk for offline              |
//|  microstructure analysis (tick speed, direction clusters, size   |
//|  anomaly, pause/entropy, spike shape).  The terminal keeps deep  |
//|  BAR history for synthetics but only shallow TICK history, so    |
//|  this stream can never be back-filled later — it must be         |
//|  captured forward.                                               |
//|                                                                  |
//|  LIGHTWEIGHT BY DESIGN:                                          |
//|  - No per-tick disk I/O.  Rows accumulate in an in-memory        |
//|    string buffer that is flushed every N ticks OR every T        |
//|    seconds, whichever comes first (v25.5: 100 ticks / 10s).      |
//|  - v25.5: file opened with FILE_SHARE_READ so the live CSV can   |
//|    be read/copied by external tools while the EA writes it.      |
//|  - Daily file rotation keeps each CSV pandas-sized.              |
//|  - Columns: ts,bid,ask,mid  (server epoch seconds, prices).      |
//|    Everything else is derivable downstream.                      |
//|  - When disabled, or when the file cannot be opened, the         |
//|    recorder degrades to a no-op: trading is never affected.      |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_TICK_RECORDER_MQH
#define MITEMSHUB_TICK_RECORDER_MQH

class CTickRecorder
{
private:
   bool     m_enabled;
   int      m_flush_every_ticks;    // flush interval in ticks
   int      m_flush_seconds;        // max seconds between flushes
   int      m_handle;               // INVALID_HANDLE when not open
   string   m_symbol;               // sanitized symbol for the file name
   string   m_day;                  // "YYYYMMDD" of the open file
   datetime m_day_start;            // server midnight of the open file
   int      m_buffered;             // rows waiting in the string buffer
   int      m_last_flush_time;      // epoch seconds of last flush
   int      m_total_recorded;       // lifetime rows (this session)
   string   m_pending;              // buffered CSV rows (no per-tick I/O)

   //--- Server-midnight epoch for the given instant
   static datetime DayStart(const datetime now)
     {
      return(now - (now % 86400));
     }

   //--- "YYYYMMDD" for the given instant (server time)
   static string DayTag(const datetime now)
     {
      MqlDateTime dt;
      TimeToStruct(now, dt);
      return(StringFormat("%04d%02d%02d", dt.year, dt.mon, dt.day));
     }

   //--- File name for a given day tag
   string FileName(const string day_tag) const
     {
      return(StringFormat("MITEMSHUB_ticks_%s_%s.csv", m_symbol, day_tag));
     }

   //--- Open (or create) today's file.  Header on first create.
   bool OpenFile(const datetime now)
     {
      m_day = DayTag(now);
      m_day_start = DayStart(now);
      // v25.5: FILE_SHARE_READ lets offline analysis tools read/copy the live
      // CSV while the EA keeps writing — without it the file is exclusively
      // locked and external readers get "device or resource busy".
      m_handle = FileOpen(FileName(m_day),
                          FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
      if(m_handle == INVALID_HANDLE)
         return(false);
      if(FileSize(m_handle) == 0)
        {
         FileSeek(m_handle, 0, SEEK_SET);
         if(FileWriteString(m_handle, "ts,bid,ask,mid\r\n") <= 0)
           {
            FileClose(m_handle);
            m_handle = INVALID_HANDLE;
            return(false);
           }
        }
      FileSeek(m_handle, 0, SEEK_END);
      return(true);
     }

   //--- Close the current file, flushing whatever remains
   void CloseFile()
     {
      if(m_handle == INVALID_HANDLE)
         return;
      FileFlush(m_handle);
      FileClose(m_handle);
      m_handle = INVALID_HANDLE;
     }

   //--- Rotate to the current day when the server day rolled over
   bool EnsureCurrentFile(const datetime now)
     {
      if(m_handle != INVALID_HANDLE && DayStart(now) == m_day_start)
         return(true);
      Flush();
      CloseFile();
      return(OpenFile(now));
     }

public:
   CTickRecorder()
     {
      m_enabled          = false;
      m_flush_every_ticks= 100;   // v25.5: tighter cadence for live analysis
      m_flush_seconds    = 10;
      m_handle           = INVALID_HANDLE;
      m_symbol           = "";
      m_day              = "";
      m_day_start        = 0;
      m_buffered         = 0;
      m_last_flush_time  = 0;
      m_total_recorded   = 0;
      m_pending          = "";
     }

   ~CTickRecorder()
     {
      Flush();
      CloseFile();
     }

   //--- Initialize.  Returns false (and disables itself) when the
   //--- first file cannot be opened; trading is unaffected either way.
   bool Init(const string symbol,
             const bool enabled,
             const int flush_every_ticks,
             const int flush_seconds)
     {
      m_enabled           = enabled;
      m_flush_every_ticks = MathMax(1, flush_every_ticks);
      m_flush_seconds     = MathMax(1, flush_seconds);
      m_symbol            = symbol;
      // Sanitize spaces/parens out of the symbol for the file name.
      StringReplace(m_symbol, " ", "_");
      StringReplace(m_symbol, "(", "");
      StringReplace(m_symbol, ")", "");
      if(!m_enabled)
         return(true);
      const datetime now = TimeCurrent();
      if(!OpenFile(now))
        {
         PrintFormat("[TickRecorder] DISABLED — cannot open %s (error %d)",
                     FileName(DayTag(now)), GetLastError());
         m_enabled = false;
         return(false);
        }
      m_last_flush_time = (int)now;
      PrintFormat("[TickRecorder] ON — %s | flush every %d ticks or %ds",
                  FileName(m_day), m_flush_every_ticks, m_flush_seconds);
      return(true);
     }

   //--- Record one tick.  Cheap: string append only.
   void OnTick(const double bid, const double ask)
     {
      if(!m_enabled)
         return;
      const datetime now = TimeCurrent();
      if(!EnsureCurrentFile(now))
        {
         // Disk hiccup: drop this tick, retry on a later tick.
         return;
        }
      const double mid = (bid + ask) / 2.0;
      m_pending += StringFormat("%I64d,%.5f,%.5f,%.5f\r\n",
                                (long)now, bid, ask, mid);
      m_buffered++;
      if(m_buffered >= m_flush_every_ticks ||
         (int)now - m_last_flush_time >= m_flush_seconds)
         Flush();
     }

   //--- Write buffered rows to disk.  Safe to call any time.
   void Flush()
     {
      if(m_handle == INVALID_HANDLE || m_buffered == 0)
         return;
      if(FileWriteString(m_handle, m_pending) > 0)
         m_total_recorded += m_buffered;
      // On write failure the buffer is dropped — the recorder never
      // blocks trading and never retries unboundedly.
      m_pending = "";
      m_buffered = 0;
      m_last_flush_time = (int)TimeCurrent();
      FileFlush(m_handle);
     }

   //--- Telemetry for the dashboard / Experts journal
   string GetDashboard() const
     {
      if(!m_enabled)
         return("TickRec: OFF");
      return(StringFormat("TickRec: %s | buffered %d | recorded %d | %s",
                          m_handle != INVALID_HANDLE ? "OPEN" : "RETRY",
                          m_buffered, m_total_recorded, FileName(m_day)));
     }

   int TotalRecorded() const { return(m_total_recorded); }
   int Buffered()      const { return(m_buffered); }
   bool IsEnabled()    const { return(m_enabled); }
};

#endif
