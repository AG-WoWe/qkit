'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 1
' Initial_Processdelay           = 500
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = High
' Version                        = 1
' ADbasic_Version                = 6.4.0
' Optimize                       = Yes
' Optimize_Level                 = 1
' Stacksize                      = 1000
' Info_Last_Save                 = JOSH-LAPTOP  JOSH-LAPTOP\joshu
'<Header End>

#Include ADwinPro_All.inc

'hard coded settings
#define output_card       3
#define output_channel    8         'Output channel for fast to zero voltage control
#define input_card        2
#define input_channel     8         'Input channel readout of voltage
#define version           02010001h 'Version: Electromigration.readout.0.1

#define process_time      2E-6      'time of one event cycle (=500kHz)
#define DAC_ZERO          32768     '16-bit zero
#define fifo_len          1000003   'fifo length

'communication PC ADwin
#define fw_version          Par_1
#define readout_active      Par_3       'readout active flag
#define emergency_stop      Par_4       'emergency stop
#define report_voltage      Par_8       'source-drain voltage to start abort script (bits)
#define voltage             Par_38      'last voltage applied
#define r_limit             FPar_1      'resist boundary to stop sweep
#define sample_rate         FPar_9      'command from PC: set sample rate (Hz) for subsampling
#define report_sample_rate  FPar_39     'report to PC: current sample rate (Hz)
#define subsampling_counter Par_40
#define fifo_raw            Data_1


'EVENT VARIABLES
dim sweep_in as long
dim subsampling_samples as long
dim fifo_raw[fifo_len] as long as fifo
#IF Processor = T12 THEN
dim resist as float32
#ELSE
dim resist as float
#ENDIF

init:
  'SET PROCESSDELAY
#IF Processor = T12 THEN
  Processdelay = process_time * 1e9
#ELSE
  Processdelay = process_time * 300e6
#ENDIF

  fw_version = version
  'CLEAR TRANSMITTION FIFO
  fifo_clear(1)

  ' INITIALIZE SUBSAMPLING
  subsampling_samples = Round(1 / (sample_rate * process_time))
  report_sample_rate = 1 / (subsampling_samples * process_time)
  subsampling_counter = 1

  emergency_stop = 0
  readout_active = 1

  'ACTIVTATE TIMER MODE FOR INPUT CARD (MUST BE AT THE END OF INIT)
  P2_ADCF_Mode(input_card, 1)

event:
  'READ INPUT
  sweep_in = P2_Read_ADCF(input_card, input_channel) '16-bit resolution
  sweep_in = sweep_in - DAC_ZERO  '-offset
  
  'CHECK VOLTAGE TO REPORT
  if (voltage >= report_voltage) then

    'CALCULATE RESISTANCE
    resist = (voltage-DAC_ZERO)/(sweep_in)

    'COMPARE WITH RESISTANCE LIMIT
    if (r_limit <= resist) then

      'SET OUTPUT TO ZERO
      P2_DAC(output_card, output_channel, DAC_ZERO)
      voltage = DAC_ZERO

      'STOP SWEEP AND READOUT PROCESS
      Stop_Process(2)
      End

    endif
    
    'SUBSAMPLE
    if (subsampling_counter = subsampling_samples) then
      'SEND DATAPOINT TO FIFO (27cycles per FIFO with no sweep)
      fifo_raw = sweep_in
      subsampling_counter = 1
    else
      Inc subsampling_counter
    endif
  endif
  
  'CHECK EMERGENCY STOP
  if (emergency_stop <> 0) then

    'SET OUTPUT TO ZERO
    P2_DAC(output_card, output_channel, DAC_ZERO)
    voltage = DAC_ZERO

    'STOP SWEEP AND READOUT PROCESS
    Stop_Process(2)
    End

  endif

finish:

  'SEND LAST INPUT TO FIFO (no subsampling!)
  fifo_raw = sweep_in

  'SET READOUT INACTIVE
  readout_active = 0
