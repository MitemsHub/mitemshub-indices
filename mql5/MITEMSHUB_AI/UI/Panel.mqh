//+------------------------------------------------------------------+
//|                                        UI/Panel.mqh              |
//|  MITEMSHUB AI MARKET ENGINE — Phase 9 UI foundation.             |
//|                                                                  |
//|  Every chart object the engine draws (dashboard labels, signal   |
//|  markers) goes through ONE lifecycle manager: a bounded, named   |
//|  object registry with LAZY ONE-TIME creation.  The contract:     |
//|                                                                  |
//|    - an object is created once, then only UPDATED (never         |
//|      re-created), so repeated Update() calls cannot leak objects;|
//|    - the registry is fixed-capacity (UI_MAX_OBJECTS), so the     |
//|      object count is provably bounded regardless of how many     |
//|      markers or refresh cycles occur;                            |
//|    - every object keeps a text cache (the value last written),   |
//|      so the unit tests can assert content headlessly even when   |
//|      the tester chart cannot materialize real objects;           |
//|    - DestroyAll() removes every managed object and resets the    |
//|      registry, so a fresh pass starts from a clean chart.        |
//|                                                                  |
//|  Why bounded: the Strategy Tester runs suites back-to-back; an   |
//|  EA that leaks one object per bar/update would exhaust the       |
//|  tester's object table mid-run and corrupt later phases.  The    |
//|  object-count tester gate (Phase9Tests) enforces the bound and   |
//|  the zero-leak teardown.                                         |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_UI_PANEL_MQH
#define MITEMSHUB_UI_PANEL_MQH

#include "../Core/Constants.mqh"

#define UI_MAX_OBJECTS  256     // hard cap on managed objects per panel
#define UI_MAX_MARKERS  64      // marker ring capacity (VisualSignals)
#define UI_TRUNCATE_LEN 34      // dashboard line width in characters

//--- string helpers shared by every UI module -------------------------------
string UITruncate(const string s, const int maxlen = UI_TRUNCATE_LEN)
  {
   if(StringLen(s) <= maxlen)
      return(s);
   return(StringSubstr(s, 0, MathMax(0, maxlen - 3)) + "...");
  }

class CUiPanel
  {
protected:
   long          m_chart;                  // chart id (0 = current)
   string        m_prefix;                 // object-name namespace
   string        m_names[UI_MAX_OBJECTS];  // managed object registry
   ENUM_OBJECT   m_types[UI_MAX_OBJECTS];  // the object type each name was created as
   string        m_text[UI_MAX_OBJECTS];   // last-written text (cache for headless tests)
   int           m_count;                  // registry size (authoritative)
   int           m_created;                // how many ObjectCreate() actually succeeded

   //--- linear registry search (registry is small and cache-hot) ------------
   int Slot(const string name) const
     {
      for(int i = 0; i < m_count; i++)
         if(m_names[i] == name)
            return(i);
      return(-1);
     }

   string Name(const int slot) const
     {
      return(m_prefix + m_names[slot]);
     }

public:
   CUiPanel()
     {
      m_chart   = 0;
      m_prefix  = "MITEMSHUB_";
      m_count   = 0;
      m_created = 0;
     }

   void Init(const long chart, const string prefix)
     {
      m_chart  = chart;
      m_prefix = prefix;
     }

   //--- registry ------------------------------------------------------------
   // One-time create: registers the name (bounded by UI_MAX_OBJECTS), then
   // attempts the real ObjectCreate.  A failed create (headless tester chart)
   // still keeps the registry slot so the managed count is deterministic and
   // the text cache stays authoritative.
   bool CreateObject(const string name, const ENUM_OBJECT type, const int subwin = 0)
     {
      if(Slot(name) >= 0)
         return(true);
      if(m_count >= UI_MAX_OBJECTS)
         return(false);
      m_names[m_count] = name;
      m_types[m_count] = type;
      m_text[m_count]  = "";
      m_count++;
      bool ok = ObjectCreate(m_chart, name, type, subwin, 0, 0);
      if(ok)
         m_created++;
      return(ok);
     }

   // Remove one object (used by the marker ring when a slot is evicted).
   void Remove(const string name)
     {
      int s = Slot(name);
      if(s < 0)
         return;
      if(m_created > 0)
         ObjectDelete(m_chart, name);
      for(int i = s; i < m_count - 1; i++)
        {
         m_names[i] = m_names[i + 1];
         m_types[i] = m_types[i + 1];
         m_text[i]  = m_text[i + 1];
        }
      m_count--;
     }

   // Tear down every managed object and reset the registry.
   // Per-object ObjectDelete (NOT ObjectsDeleteAll-with-prefix): measured in
   // the tester, prefix bulk-delete silently fails to release some objects
   // (the object-count gate caught a 50-object leak), while per-object
   // ObjectDelete — the path Remove() and the marker ring use — always
   // releases.  Deleting exactly what we manage is also safer than a prefix
   // sweep, which could nuke another panel's objects sharing the prefix.
   void DestroyAll()
     {
      if(m_created > 0)
        {
         for(int i = 0; i < m_count; i++)
            ObjectDelete(m_chart, m_prefix + m_names[i]);
        }
      m_count   = 0;
      m_created = 0;
      if(m_chart != 0)
         ChartRedraw(m_chart);
     }

   int  Count() const       { return(m_count); }
   int  CreatedCount() const{ return(m_created); }
   long Chart() const       { return(m_chart); }
   string Prefix() const    { return(m_prefix); }

   //--- content -------------------------------------------------------------
   // Write text to a managed object.  The text cache is updated FIRST and
   // unconditionally (headless-safe); the real object update is attempted
   // only when the terminal actually created objects.
   bool SetText(const string name, const string text,
                const color clr = clrSilver, const int fontsize = 9,
                const bool bold = false)
     {
      int s = Slot(name);
      if(s < 0)
         return(false);
      m_text[s] = text;
      if(m_created <= 0)
         return(true);
      bool ok = true;
      ok &= ObjectSetString(m_chart, name, OBJPROP_TEXT, text);
      ok &= ObjectSetInteger(m_chart, name, OBJPROP_COLOR, (long)clr);
      ok &= ObjectSetInteger(m_chart, name, OBJPROP_FONTSIZE, fontsize);
      if(bold)
        {
         ok &= ObjectSetString(m_chart, name, OBJPROP_FONT, "Arial Bold");
        }
      else
        {
         ok &= ObjectSetString(m_chart, name, OBJPROP_FONT, "Arial");
        }
      return(ok);
     }

   // Position a managed label/rectangle object (corner 0 = top-left).
   bool MoveTo(const string name, const int x, const int y)
     {
      if(Slot(name) < 0)
         return(false);
      if(m_created <= 0)
         return(true);
      bool ok = true;
      ok &= ObjectSetInteger(m_chart, name, OBJPROP_XDISTANCE, x);
      ok &= ObjectSetInteger(m_chart, name, OBJPROP_YDISTANCE, y);
      return(ok);
     }

   // Generic property write (used by VisualSignals for arrow codes / styles).
   bool SetInt(const string name, const ENUM_OBJECT_PROPERTY_INTEGER prop,
               const long value)
     {
      if(Slot(name) < 0)
         return(false);
      if(m_created <= 0)
         return(true);
      return(ObjectSetInteger(m_chart, name, prop, value));
     }

   bool SetDouble(const string name, const ENUM_OBJECT_PROPERTY_DOUBLE prop,
                  const double value)
     {
      if(Slot(name) < 0)
         return(false);
      if(m_created <= 0)
         return(true);
      return(ObjectSetDouble(m_chart, name, prop, value));
     }

   //--- headless-readable state ----------------------------------------------
   string GetCachedText(const string name) const
     {
      int s = Slot(name);
      if(s < 0)
         return("");
      return(m_text[s]);
     }

   bool Has(const string name) const   { return(Slot(name) >= 0); }

   // Object type a registered name was created as; -1 when unregistered.
   // (ENUM_OBJECT has no OBJ_NO_OBJECTS sentinel in this build.)
   int CachedType(const string name) const
     {
      int s = Slot(name);
      if(s < 0)
         return(-1);
      return((int)m_types[s]);
     }
  };

#endif // MITEMSHUB_UI_PANEL_MQH
