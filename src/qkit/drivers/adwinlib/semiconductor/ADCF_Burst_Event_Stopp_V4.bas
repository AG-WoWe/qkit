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


Dim data[memory_size] as Long                                 'destination array of one average of the pulse train
Dim pattern as Long                                           'bit pattern to address one module
Dim rest as Long                                              'rest of samples that still need to be aquired by the burst
Dim counter_sleep as Long                                     'used for variable sleep times before triggering AWG
#Define trigger_on Par_20                                     'If Par_20=1 then trigger is send to awg


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
  counter_sleep = 1
  
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
  Processdelay = 1e6 'so high to allow time for P2_Burst_Read_
  
  Selectcase flag_start_measurement
    Case 1 'trigger AWG with DIG OUT 0
      IF (repeats_to_do>0) Then
        flag_finished_ADC = 0
        flag_start_measurement = 0
        repeats_to_do = repeats_to_do - 1
        measurements_done = 0
        
        'Par_28 = repeats_to_do 'debug
        
        'resetting trigger to AWG, very important info for BUS, P2_Sleep is only working between BUS operations!
        'CPU_Digout(0,0) 
        
        'sending trigger to AWG:
        trigger_on = 1 'start sending triggers
        
        'Inc Par_29 'debug
      Else
        flag_finished = 1
        End   'End this process, measurement done
      EndIf
      
      
    Case 0 'readout of the ADC when pulse train is done:      
      rest = P2_Burst_Status(module)
   
      'Par_31 = rest 'debug
    
      If (rest=0) Then
        IF (measurements_done=number_of_measurements) Then
          'The memory of the Input card F-4/16 is 256MB so it will hold upto 130 M Samples. 
          P2_Burst_Read_Unpacked1(module, sample_length*number_of_measurements, 0, data, 1, 3)
 
          flag_finished_ADC = 1
          index_to_write = 0 'sets back memory index of burst readout of second process  
        
          'Let the PC get the Data.... 
          'Then PC sets flag_start_measurement to 1
      
          'Inc Par_32 'debug
          
        EndIf
      EndIf
  EndSelect
  
  
  
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
