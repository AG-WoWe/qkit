'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 3
' Initial_Processdelay           = 3000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = Low
' Priority_Low_Level             = 1
' Version                        = 1
' ADbasic_Version                = 6.3.1
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = PHI-LIUS  KIT\hp3117
'<Header End>
#Include ADwinPro_All.Inc
#define do_trigger Par_30

Init:
#IF Processor = T12 THEN
  Processdelay = 1E6 ' 1ms process cycle
#ELSE
  Processdelay = 3E5 ' 1ms process cycle
#ENDIF

  '' set DIG I/O-0 as output
  CPU_Dig_IO_Config(11b)
  
Event:
  if (do_trigger = 1) then
    CPU_Digout(0, 1) 'Set DIG I/O 1 to TTL level high
    P2_Sleep(14) ' Wait 140ns (minimum allowed waiting time)
    CPU_DIgout(0, 0) 'Set DIG I/O 1 to TTL level low
    do_trigger = 0
  endif

Finish:
