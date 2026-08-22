//+------------------------------------------------------------------+
//|                                   Tests/MitemshubAIBacktest.mq5  |
//|  Phase 10: compile + run the production integration EA in the    |
//|  Strategy Tester.  The EA code lives in ../MitemshubAI.mq5; this |
//|  wrapper exists so verify_all.ps1's Tests/*Tests.mq5 discovery   |
//|  picks it up.  The [PHASE10] machine lines in the tester log are |
//|  the cross-validation contract.                                  |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 10 integration EA (tester wrapper)"

#include "../MitemshubAI.mq5"
