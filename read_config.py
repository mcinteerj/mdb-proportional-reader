#!/usr/bin/env python3

read_ratio_list = [20,10,5]
docs_ratio_list = [5,5,10]

read_duration_seconds = 120
result_bucket_duration_secs = 15

processes  = 4
threads_per_process = 2

# With curses mode enabled(true), curses are used to show interim status on screen
# with curses mode disabled(false), results will be repeatedly printed
curses_mode = False

# This buffer is the period of time between when all processes have reported themselves to the coordination function and the beginning of the test
# It needs to exist as it gives each execution process time to detect the start/end times of the test and intialise a number of execution settings
pre_start_buffer_secs = 2

response_metrics_batch_size = 400