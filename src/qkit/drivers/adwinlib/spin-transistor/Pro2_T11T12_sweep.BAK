'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 2
' Initial_Processdelay           = 50000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = Low
' Priority_Low_Level             = 1
' Version                        = 1
' ADbasic_Version                = 6.4.0
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = DESKTOP-0M2IFQQ  DESKTOP-0M2IFQQ\kaptn
'<Header End>
'Sweeps for spin transistor measurements written by Luca Kosche in April 2024
'This script is written sweep up to all outputs in the most efficient way on T11 and 16-bit output card.
'If the lockin process is active, the lockin channel is not set by this script, but the bias value is set,
'which is handled by the locking.
'At the end of each sweep the current outputs are saved to the sweep_start array which serve as new starting point
'for the next sweep, if nothing else is given by the PC. Problems can arise after repowering or rebooting the adwin,
'because the sweep_start array might not be filled with the ecpected values.

#Include ADwinPro_All.Inc

#define process_time       200E-6   '-> sweep update rate = 5kHz (must be high enough to don't overload ADwin)
#define DAC_ZERO           32768
#define output_card        3
#define nb_outs            8        'number of outputs
#define version            01020001h'Version Spintransistor.Sweep.0.1

#define fw_version         Par_2    'adbasic version of process_number 2

#define lockin_active      Par_3    'reported from lockin process, that lockin is running
#define meas_active        Par_4    'command lockin process to send values to PC (while "1")

#define sweep_active       Par_11   'command from PC to start sweep AND report from process if sweep is active
#define sweep_duration     FPar_11  'command from PC: sweep_duration of the sweep (s)
#define report_duration    FPar_12  'report: real sweep_duration of the sweep (s)
#define sweep_target       Data_11  'command from PC: target output values of sweep

#define out1               Par_31   'store current outputs (FASTEST and accesible by PC)
#define out2               Par_32   '      ''
#define out3               Par_33   '      ''
#define out4               Par_34   '      ''
#define out5               Par_35   '      ''
#define out6               Par_36   '      ''
#define out7               Par_37   '      ''
#define out8               Par_38   '      ''



dim start1, start2, start3, start4, start5, start6, start7, start8, cycle, steps as long
dim inc1, inc2, inc3, inc4, inc5, inc6, inc7, inc8 as float
#IF Processor = T12 THEN
dim sweep_target[nb_outs] as long
#ELSE
dim sweep_target[nb_outs] as long at dm_local 
#ENDIF

init:
  'SET PROCESSDELAY
#IF Processor = T12 THEN
  Processdelay = Round(process_time * 1E9)
#ELSE
  Processdelay = Round(process_time * 300E6)
#ENDIF
  
  steps = Round(sweep_duration / process_time)
  report_duration = steps * process_time
  
  ' SET START VALUES OF THE SWEEP
  start1 = out1
  start2 = out2
  start3 = out3
  start4 = out4
  start5 = out5
  start6 = out6
  start7 = out7
  start8 = out8
  
  ' SET INCREMENT VALUES OF THE SWEEP
  inc1 = (sweep_target[1] - start1) / steps
  inc2 = (sweep_target[2] - start2) / steps
  inc3 = (sweep_target[3] - start3) / steps
  inc4 = (sweep_target[4] - start4) / steps
  inc5 = (sweep_target[5] - start5) / steps
  inc6 = (sweep_target[6] - start6) / steps
  inc7 = (sweep_target[7] - start7) / steps
  inc8 = (sweep_target[8] - start8) / steps
    
  cycle = 0
  fw_version = version
  sweep_active = 0
  
event:
  if (sweep_active = 0) then
    'Do nothing
  else
    ' SET MEASUREMENT FLAG TO START MEASUREMENT
    meas_active = 1  
  
    ' GO TO THE NEXT CYCLE OR END PROCESS
    if (cycle = steps) then
      meas_active = 0 'set measurement active flag as early as possible to prevent sending extra data to PC
      sweep_active = 0
      end
    else
      Inc cycle
    endif
    
    ' CALCULATE NEW OUTPUTS AND WRITE TO PAR_1 - Par_8
    out1 = start1 + inc1 * cycle
    out2 = start2 + inc2 * cycle
    out3 = start3 + inc3 * cycle
    out4 = start4 + inc4 * cycle
    out5 = start5 + inc5 * cycle
    out6 = start6 + inc6 * cycle
    out7 = start7 + inc7 * cycle
    out8 = start8 + inc8 * cycle
    
    ' SET ALL OUTPUTS EXCEPT LOCKIN CHANNEL (123 cycles)
    ' this is the fastest way i found for T11 and F8/18
    P2_DAC(output_card, 1, out1)
    P2_DAC(output_card, 2, out2)
    P2_DAC(output_card, 3, out3)
    P2_DAC(output_card, 4, out4)
    P2_DAC(output_card, 5, out5)
    P2_DAC(output_card, 6, out6)
    P2_DAC(output_card, 7, out7)
    
    'ONLY SET DAC OUTPUT IF LOCKIN IS INACTIVE
    if (lockin_active = 0) then
      P2_DAC(output_card, 8, out8)
    endif
    
  endif
  
finish:                               

