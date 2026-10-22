'<ADbasic Header, Headerversion 001.001>
' Process_Number                 = 3
' Initial_Processdelay           = 2000
' Eventsource                    = Timer
' Control_long_Delays_for_Stop   = No
' Priority                       = Low
' Priority_Low_Level             = 1
' Version                        = 1
' ADbasic_Version                = 6.4.0
' Optimize                       = Yes
' Optimize_Level                 = 4
' Stacksize                      = 1000
' Info_Last_Save                 = DESKTOP-VJN2OMA  DESKTOP-VJN2OMA\nanospin
'<Header End>
'Process triggers the AWG pulse train and reads out the ADC afterwards.
'requires ADCF_Burst_Event_V3.bas to start burst measurement. 

#Include ADwinPro_All.Inc

#Define module 15                                             'number given to the card 1-15, we use it as 15 always                            
#Define data Data_1                                           'receives values of channel 1
#Define sample_length Par_10                                  'HAS TO BE DIVISIBLE BY 8 if one channel is read only, or divisible by 4 if more are read
#Define number_of_measurements Par_11                         'number of pulses in pulsetrain of AWG
#Define number_of_repeats Par_12                              'number of triggers sent to the AWG in order to trigger a pulse train
#Define measurements_done Par_13                              'SHARED WITH OTHER PROCESS! tells how many measurments (triggers for one pulse train) are already measured
#Define repeats_to_do Par_14                                  'shared with PC, number of averages of the pulse train that need to be done still
#Define memory_size 1e8                                       'size of Memory block for full measurement (about 10 events), multiple of 4
#Define index_to_write Par_15                                 'SHARED WITH OTHER PROCESS!'index in Card memory where to write to

#Define flag_finished_ADC Par_16                              'indicates the PC that the data is ready to be transferred
#Define flag_error Par_17                                     'is 1 if things go wrong
#Define flag_start_measurement Par_18                         'can only be changed to 1 by the PC. if 1, the ADwin sends a trigger to the AWG
#Define flag_finished Par_19                                  'if 1, the whole measurement with all averages is done.
#Define trigger_on Par_20                                     'If Par_20=1 then trigger is send to awg


Dim data[memory_size] as Long                                 'destination array of one average of the pulse train
Dim pattern as Long                                           'bit pattern to address one module
Dim rest as Long                                              'rest of samples that still need to be aquired by the burst


Init:
  Processdelay = 10000
  'initializing random numbers for timedelay of trigger to AWG
  'they are even and below 1e5 
  'python: for index in range(1, 1001):
  'print("random_even_numbers[", index, "] = ", round(np.random.rand()*5e4)*2 )

  P2_SET_LED(module, 1)
  pattern = Shift_Left(1,module-1) 'makes 100000000000000
  
  measurements_done = 0
  repeats_to_do = number_of_repeats
  
  flag_finished_ADC = 0
  flag_error = 0
  flag_start_measurement = 0
  flag_finished = 0
  index_to_write = 0
  
  'CPU Digital output 0 to trigger the AWG
  trigger_on = 0 'not sending trigger to AWG at first
  CPU_Dig_IO_Config(01b)
  CPU_Digout(0,0)
    
  'Par_28 = 0 'debug
  'Par_29 = 0 'debug
  'Par_30 = 0 'debug
  'Par_31 = 0 'debug
  'Par_32 = 0 'debug
  'Par_5 = 0  'debug
  
  
Event: 
  Processdelay = 1e4 'so high to allow time for P2_Burst_Read_ 
  'does not need to be 1e6 or 1e7, processdelay only says how long one cycle have to be at least,
  'if P2_Burst_Read_ will need longer it will take its time, but importent for timing between measurements
  
  'Only allow readout after new measurement is started, so we do not override old data, before the data aquisation by the PC is done
  If (flag_finished_ADC = 0) Then
    'check if all burst measurements were started
    If (measurements_done >= number_of_measurements) Then
      'check if last burst measurement is finished
      If (P2_Burst_Status(module) = 0) Then
        
        P2_Burst_Read_Unpacked1(module, sample_length*number_of_measurements, 0, data, 1, 3)
        flag_finished_ADC = 1   'set readout ready flag true
      
      EndIf
    EndIf
  EndIf

  'Start new measurement (PC does readout data before starting a new measurement, so there is no data loss (hopefully))
  If (flag_start_measurement = 1) Then
    IF (repeats_to_do>0) Then
      flag_finished_ADC = 0       'reset readout ready flag
      flag_start_measurement = 0  'reset start measurement flag
      index_to_write = 0          'reset memory index of burst readout of second process 
      measurements_done = 0       'reset counter of done measurements
      repeats_to_do = repeats_to_do - 1   'decrease repeat counter

      trigger_on = 1              'set AWG trigger flag true
    Else
      flag_finished = 1
      End   'End this process, measurement done
    EndIf
  EndIf

  'Edge Triggering the AWG with Dig IO 0: trigger_on is set to 0 with other process that does the burst measurement
  Selectcase trigger_on
    Case 0 'not sending trigger to AWG
      CPU_Digout(0,0)
    Case 1  'send trigger to AWG
      CPU_Digout(0,1)
      P2_Sleep(100) 'even and in units of 10ns
      CPU_Digout(0,0)
  EndSelect

  'error handling: too many triggers to ADwin
  'IF (measurements_done>number_of_measurements) Then 
  '  flag_error = 1
  'EndIf
  
Finish:
  P2_SET_LED(module, 0)
