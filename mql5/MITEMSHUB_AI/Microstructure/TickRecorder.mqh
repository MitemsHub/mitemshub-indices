//+------------------------------------------------------------------+
//|                                    Microstructure/TickRecorder.mqh    |
//|  MITEMSHUB AI — ALWAYS-ON TICK RECORDER (v25.9)                  |
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
//|                                                                  |
//|  v26.16 — MULTI-SESSION VERDICT COLLECTION:                      |
//|  - The tick-fade verdict must rest on more than 3 days of data.  |
//|    This version adds per-session statistics (ticks, spikes,      |
//|    gaps, first/last ts) so the offline verdict script can sum    |
//|    coverage without re-reading every CSV.                        |
//|  - Session summary logged at day-rollover AND on Flush() every   |
//|    ~5 minutes, so partial sessions are visible in the journal    |
//|    even if the terminal crashes before midnight.                 |
//|  - Recording gaps (terminal closed, weekend, disconnection) are  |
//|    counted and reported — the verdict script excludes sessions   |
//|    whose live coverage falls below a minimum threshold.          |
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
   int      m_open_failures;        // v25.8: consecutive open failures (backoff)
   int      m_next_retry_time;      // v25.8: epoch of next open attempt
   int      m_next_warn_time;       // v25.8: throttle repeated warnings

   //--- v26.16: per-session statistics (multi-session verdict collection)
   int      m_session_spikes;       // tick jumps >= spike threshold (approx: |jump| >= 3.0 pts)
   int      m_session_gaps;         // recording gaps > 60s (terminal closed / disconnect)
   datetime m_session_first_ts;     // first tick of the session
   datetime m_session_last_ts;      // last tick of the session
   datetime m_session_last_tick;    // previous tick ts (gap detection)
   int      m_last_summary_time;    // epoch of last periodic summary log
   double   m_last_bid;             // v26.16: previous tick bid (jump computation)

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
   //--- v25.9: never clobber a live handle on failure — commit locally.
   bool OpenFile(const datetime now)
     {
      m_day = DayTag(now);
      m_day_start = DayStart(now);
      // v25.5: FILE_SHARE_READ lets offline analysis tools read/copy the live
      // CSV while the EA keeps writing — without it the file is exclusively
      // locked and external readers get "device or resource busy".
      const int h = FileOpen(FileName(m_day),
                             FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
      if(h == INVALID_HANDLE)
         return(false);
      m_handle = h;
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

   //--- v25.8: open attempt with retry bookkeeping; false on failure.
   //--- A transient 5004 (file briefly locked by a reader/AV scan) used to
   //--- disable the recorder forever; now it retries from later ticks.
   bool TryReopen(const datetime now)
     {
      if(OpenFile(now))
         return(true);
      m_open_failures++;
      int       shift   = MathMin(m_open_failures, 4);   // 15s -> 30 -> 60 -> 120 -> 240s
      const int backoff = 15 * (1 << shift);
      m_next_retry_time = (int)now + backoff;
      if((int)now >= m_next_warn_time)
        {
         PrintFormat("[TickRecorder] open failed (error %d) — will retry in %ds (attempt %d)",
                     GetLastError(), backoff, m_open_failures);
         m_next_warn_time = (int)now + 300;             // warn at most every 5 minutes
        }
      return(false);
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
      m_open_failures    = 0;
      m_next_retry_time  = 0;
      m_next_warn_time   = 0;
      m_session_spikes   = 0;
      m_session_gaps     = 0;
      m_session_first_ts = 0;
      m_session_last_ts  = 0;
      m_session_last_tick= 0;
      m_last_summary_time= 0;
      m_last_bid          = 0.0;
     }

   ~CTickRecorder()
     {
      Flush();
      CloseFile();
     }

   //--- Initialize.  Safe to call again on a persistent object (v25.9):
   //--- closes any stale handle first, then retries transient open failures.
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
      CloseFile();                       // v25.9: re-init (param confirm / TF change) keeps globals
                                         // alive — closing the stale handle first stops the 5004-forever lock
      m_open_failures  = 0;
      m_next_warn_time = 0;
      if(!TryReopen(now))
        {
         // v25.8: keep recording enabled — retry automatically on later ticks.
         return(true);
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
      if(m_handle == INVALID_HANDLE)
        {
         // v25.8: transient open failure — retry with backoff, never self-disable.
         if((int)now < m_next_retry_time)
            return;                            // ticks are skipped while unavailable
         if(!TryReopen(now))
            return;
         PrintFormat("[TickRecorder] RECOVERED — %s open after %d failed attempt(s)",
                     FileName(m_day), m_open_failures);
         m_open_failures = 0;
        }
      if(!EnsureCurrentFile(now))
        {
         // Disk hiccup (e.g. day-rollover open race): drop this tick,
         // back off and retry on a later tick.
         m_open_failures++;
         m_next_retry_time = (int)now + 30;
         return;
        }
      const double mid = (bid + ask) / 2.0;
      // v26.16: compute tick-to-tick jump for spike/gap statistics
      const double jump = (m_session_last_tick > 0) ? (bid - m_last_bid) : 0.0;
      m_last_bid = bid;
      CountSpike(now, jump);
      m_pending += StringFormat("%I64d,%.5f,%.5f,%.5f\r\n",
                                (long)now, bid, ask, mid);
      m_buffered++;
      MaybeLogSessionSummary(now);
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

   //--- v26.16: spike/gap counter fed from OnTick (cheap threshold, matches
   //    the verdict script's |jump| >= 3.0 pts approximation)
   void CountSpike(const datetime now, const double jump)
     {
      if(MathAbs(jump) >= 3.0)
         m_session_spikes++;
      // Gap detection: a gap > 60s means the terminal was closed or the
      // connection dropped — the verdict script excludes sessions whose
      // live coverage falls below a minimum threshold.
      if(m_session_last_tick > 0 && now - m_session_last_tick > 60)
         m_session_gaps++;
      m_session_last_tick = now;
      if(m_session_first_ts == 0)
         m_session_first_ts = now;
      m_session_last_ts = now;
     }

   //--- v26.16: periodic per-session summary in the Experts journal, so a
   //    partial session is visible even if the terminal crashes before
   //    midnight.  Logged at most every 5 minutes of recording activity.
   void MaybeLogSessionSummary(const datetime now)
     {
      if(m_last_summary_time == 0)
         m_last_summary_time = (int)now;
      if((int)now - m_last_summary_time < 300)
         return;
      m_last_summary_time = (int)now;
      PrintFormat("[TickRecorder] SESSION SUMMARY: %s | ticks %d | spikes %d | "
                  "gaps %d | span %ds -> %ds | %s",
                  m_day, m_total_recorded, m_session_spikes, m_session_gaps,
                  (int)m_session_first_ts, (int)m_session_last_ts, FileName(m_day));
     }

   //--- v26.16: per-session statistics accessors for the verdict script
   int      SessionSpikes()   const { return(m_session_spikes); }
   int      SessionGaps()     const { return(m_session_gaps); }
   datetime SessionFirstTs()  const { return(m_session_first_ts); }
   datetime SessionLastTs()   const { return(m_session_last_ts); }
};

#endif
