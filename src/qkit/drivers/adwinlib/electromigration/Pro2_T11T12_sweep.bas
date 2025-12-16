'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 2
' Initial_Processdelay           = 5000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = Low
' Priority_Low_Level             = 1
' Version                        = 1
' ADbasic_Version                = 6.4.0
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = DESKTOP-H3MR9LF  DESKTOP-H3MR9LF\joshu
'<Header End>

'Electromigration for spin transistor written by Joshua Gabriel in January 2025
'This script is written sweep up the source-drain voltage and optioanal gate voltage
'on T11 or T12 and 16-bit output card.
'The sweep ends when the resistance reaches a predefined maximum threshold,
'the source-drain voltage reaches its maximum or it is stopped manually.

' Idea:
'   * voltage sweep output on output_channel (8)
'   * measure input at input_channel
'   * calculation of resistance

' Background of implementation:
'   * Slow sweep with fast readout
'   * -> low priority process with processdelay dependent on the sweep rate for slow sweeps with minimal voltage steps
'   * -> fast high priority process for readout and resistance calculation to stop immediately if the resistance limit is reached


#Include ADwinPro_All.inc

#define DAC_ZERO          32768     '16-bit zero
#define output_card       3
#define output_channel    8
#define gate_channel      7
#define version           02020001h 'Version Electromigration.Sweep.0.1

'communication PC ADwin
#define fw_version          Par_2
#define gate2zero_dur       Par_10      'duration for gate to sweep back to zero
#define sweep_active        Par_11      'voltage ramp active flag
#define max_voltage         Par_18      'maximal source-drain voltage (bits)
#define gate_voltage        Par_37      'last gate voltage applied
#define voltage             Par_38      'last source-drain voltage applied
#define gate_scale          FPar_20     'scale of gate voltage sweep
#define sweep_rate          FPar_21     'sweep rate to calculate minimal processdelay


'EVENT VARIABLES
dim step_i as long

'FINISH VARIABLES
dim i, max_steps, sleep_time as long

init:
  'SET PROCESSDELAY
#IF Processor = T12 THEN
  Processdelay = Round(1E9/sweep_rate)
#ELSE
  Processdelay = Round(300E6/sweep_rate)
#ENDIF

  fw_version = version
  step_i = 0

  'CALCULATE FIRST VALUE FOR SWEEP
  voltage = DAC_ZERO + step_i
  gate_voltage = DAC_ZERO + Round(gate_scale * step_i)

event:  
  'SET OUTPUT
  P2_DAC(output_card, output_channel, voltage)
  P2_DAC(output_card, gate_channel, gate_voltage)

  'SET NEXT VALUE FOR SWEEP
  Inc step_i
  Inc voltage
  gate_voltage = DAC_ZERO + Round(gate_scale * step_i)

  'CHECK MAX VOLTAGE
  if (voltage >= max_voltage) then

    'SET SOURCE-DRAIN OUTPUT TO DAC_ZERO
    P2_DAC(output_card, output_channel, DAC_ZERO)
    voltage = DAC_ZERO
    'STOP READOUT (1) AND SWEEP PROCESS
    Stop_Process(1)
    End

  endif
  
finish:

  'SET SOURCE-DRAIN OUTPUT TO DAC_ZERO
  P2_DAC(output_card, output_channel, DAC_ZERO)
  voltage = DAC_ZERO

  if (gate_scale <> 0) then

    'CALCULATE STEPSIZE AND SLEEP_TIME FOR GATE SWEEP LOOP
    max_steps = gate_voltage - DAC_ZERO
    sleep_time = Round(gate2zero_dur * 1E8/ max_steps)
    
    'START RAMPING GATE TO ZERO
    for i = 1 to max_steps

      'CALCULATE NEW OUTPUT FOR GATE VOLTAGE
      gate_voltage = gate_voltage - 1

      'SET OUTPUT IF >= DAC_ZERO, ELSE SET DAC_ZERO
      if (gate_voltage >= DAC_ZERO) then
        P2_DAC(output_card, gate_channel, gate_voltage)
      else
        P2_DAC(output_card, gate_channel, DAC_ZERO)
      endif

      'CPU SLEEP TO SLOW DOWN SWEEP
      CPU_sleep(sleep_time)

    next i

    'SET GATE OUTPUT TO DAC_ZERO
    P2_DAC(output_card, gate_channel, DAC_ZERO)

    'RESET SWEEP ACTIVE FLAG
    sweep_active = 0

  endif
  
