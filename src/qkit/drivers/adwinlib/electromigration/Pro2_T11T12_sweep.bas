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
' Info_Last_Save                 = JOSH-LAPTOP  JOSH-LAPTOP\joshu
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

#define process_time      200E-6  '-> sweep update rate = 5kHz (must be high enough to don't overload ADwin)
#define DAC_ZERO          32768     '16-bit zero
#define output_card       3
#define gate_channel      7
#define output_channel    8
#define version           02020001h 'Version Electromigration.Sweep.0.1

'communication PC ADwin
#define fw_version          Par_2
#define sweep_active        Par_13      'voltage ramp active flag
#define gate2zero_dur       Par_17      'duration for gate to sweep back to zero
#define gate_voltage        Par_37      'last gate voltage applied
#define max_voltage         Par_18      'maximal source-drain voltage (bits)
#define voltage             Par_38      'last source-drain voltage applied
#define gate_scale          FPar_10     'scale of gate voltage sweep
#define sweep_rate          FPar_21     'sweep rate (V/s)
#define report_rate         FPar_22     'report: real sweep_rate of the sweep (V/s)

'EVENT VARIABLES
dim cycle, steps as long
dim inc_voltage, inc_gate as float

'FINISH VARIABLES
dim i, gate_steps, sleep_time as long

init:
  'SET PROCESSDELAY
#IF Processor = T12 THEN
  Processdelay = Round(1E9*process_time)
#ELSE
  Processdelay = Round(300E6*process_time)
#ENDIF

  fw_version = version
  steps = Round(((max_voltage-DAC_ZERO) / sweep_rate)/process_time) 'number of steps for sweep up to test voltage with given sweep rate and process_time
  inc_voltage = (max_voltage-DAC_ZERO) / steps 'voltage increase per step
  inc_gate = inc_voltage * gate_scale 'gate voltage increase per step (if gate_scale is given)

  voltage = DAC_ZERO
  gate_voltage = DAC_ZERO

event:
  sweep_active = 1
  P2_DAC(output_card, output_channel, voltage)
  P2_DAC(output_card, gate_channel, gate_voltage)

  if (cycle = steps) then
    'SET SOURCE-DRAIN OUTPUT TO DAC_ZERO
    P2_DAC(output_card, output_channel, DAC_ZERO)
    voltage = DAC_ZERO
    'STOP READOUT (1) AND SWEEP PROCESS
    Stop_Process(1)
    End
  else
    Inc cycle
  endif

  voltage = DAC_ZERO + cycle * inc_voltage
  gate_voltage = DAC_ZERO + cycle * inc_gate
  
finish:
  'SET SOURCE-DRAIN OUTPUT TO DAC_ZERO
  P2_DAC(output_card, output_channel, DAC_ZERO)
  voltage = DAC_ZERO

  if (gate_scale <> 0) then
    'CALCULATE STEPS OF GATE SWEEP BACK TO ZERO
    sleep_time = Round(gate2zero_dur * 1E8/ cycle)
    
    'START RAMPING GATE TO ZERO
    for i = 1 to gate_steps

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
  endif

  'SET GATE OUTPUT TO DAC_ZERO
  P2_DAC(output_card, gate_channel, DAC_ZERO)

  'RESET SWEEP ACTIVE FLAG
  sweep_active = 0
