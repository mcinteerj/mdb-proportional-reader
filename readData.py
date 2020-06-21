#!/usr/bin/env python3
from pymongo import MongoClient
from multiprocessing import Process, Queue
from threading import Thread
import multiprocessing
import threading
import random
import datetime
import json
import math
import time
from prettytable import PrettyTable
import os
import global_config
import read_config
import sys
import curses

def main():
    # Retrieve basic read configuration from config file
    print("Retrieving read config....")
    read_duration_seconds = read_config.read_duration_seconds

    read_procs = read_config.read_procs
    threads_per_read_proc = read_config.threads_per_read_proc

    read_ratio_list = read_config.read_ratio_list
    docs_ratio_list = read_config.docs_ratio_list

    # Count docs in collection (informs reading_group Ranges)
    print("Counting Existing Documents in Collection")
    total_docs = get_doc_count()
    
    # Create reading groups (function returns a list of reading group dicts)
    print("Creating Reading Groups")
    reading_groups_list = get_reading_groups_list(read_ratio_list, docs_ratio_list, total_docs)

    # Print reading groups (formatted as table)
    print_reading_groups(reading_groups_list)

    # Create a multi-proc manager to manage a shared dictionary between processes
    manager = multiprocessing.Manager()

    # Create a managed/shared dict 
    coordination_dict = manager.dict({
        'start_time': False,
        'end_time': False,
        'reading_groups_list': reading_groups_list,
        'read_procs': read_procs,
        'threads_per_read_proc': threads_per_read_proc,
        'total_read_threads': read_procs * threads_per_read_proc,
        'thread_states': manager.dict(),
        'results': {}
    })

    # Create a queue for each process to add response metrics results to
    response_metrics_queue = Queue()

    # Create a process_list
    process_list = []

    # Add a coordination process to the process list
    process_list.extend([Process(target=results_handler,args=(response_metrics_queue, coordination_dict))])
    
    # Add query execution process(es) to the process list
    process_list.extend(get_query_execution_processes(response_metrics_queue, coordination_dict))
    
    # Start all processes
    start_processes(process_list)
    
    # Start the process coordinator
    process_coordinator(response_metrics_queue, coordination_dict, read_duration_seconds)
    
    # Join all processes
    join_processes(process_list)

def get_doc_count():
    # Define the mongoclient/collection
    coll = get_mongo_collection()

    # Return the count of docs in collection
    return coll.estimated_document_count()

def get_reading_groups_list(read_ratio_list, docs_ratio_list, totalDocs):
    # read_ratio_list and docs_ratio_list must have the same length
    # each pair of entries (one from each list) generates a docreading_group
    if (len(read_ratio_list) != len(docs_ratio_list)):
        print()
        print("read_ratio_list (length: " + str(len(read_ratio_list)) + ") and docs_ratio_list (length: " + str(len(docs_ratio_list)) + ") must be the same length")
        sys.exit("Error in read_config file")
    
    reading_groups_list = []

    # For each entry in the read_ratio_list
    for i in range(len(read_ratio_list)):
        # proportions = entry / sum of entries
        docs_proportion = (docs_ratio_list[i] / sum(docs_ratio_list))
        read_proportion = (read_ratio_list[i] / sum(read_ratio_list))

        if (len(reading_groups_list) == 0):
            # Set lower boundary of range to 0 if first entry in list
            lower = 0
        else:
            # Set lower boundry of range to upper boundary of previous entry in list
            lower = reading_groups_list[-1]["docs_upper"]
        
        # Set upper to the lower plus an increment based on docsRatio * totalDocs
        upper = lower + (math.floor(docs_proportion * totalDocs))

        # Add reading group to list
        reading_groups_list.append({
            "reading_group_id": i,
            "read_proportion": read_proportion,
            "docs_lower": lower,
            "docs_upper": upper,
            "docs_in_range": (upper - lower)
            })

    # Return list of reading groups
    return reading_groups_list

def print_reading_groups(reading_groups_list):
    # Initialise the PrettyTable
    table = PrettyTable()
    
    # Set the table title
    table.title = "Reading Groups"

    # Initialise the fields list
    fields = []

    # Add each key in the first read_ratio_list as fields to the table
    for key in reading_groups_list[0].keys():
        fields.append(key)
    table.field_names = fields
    
    # For each item in the reading_groups list add a row to the table
    for reading_group in reading_groups_list:
        row = []

        # Add the values of each field to the row list
        for field in reading_group:
            row.append(reading_group[field])
        
        # add the row to the table
        table.add_row(row)

    print()
    print(table)
    print()

def get_query_execution_processes(response_metrics_queue, coordination_dict):
    # Initialise process list
    process_list = []
    
    # Add a read process to the list based on the number of read_procs defined
    for p in range(coordination_dict['read_procs']):
        process = Process(target=begin_query_execution_threads,args=(response_metrics_queue, coordination_dict))
        process_list.append(process)

    # Return the list of processes
    return process_list

def start_processes(process_list):
    # Start each process in the list
    for process in process_list:
        process.start()

def results_handler(response_metrics_queue, coordination_dict):
    # Define basic thread info
    current_proc_id = multiprocessing.current_process().pid
    current_thread_id = str(current_proc_id) + "-" + str(threading.current_thread().ident)

    # As sub-objects within multiprocessing managed dicts cannot be updated by individual field,
    # This will instantiate a dict used to represent the state of this thread
    # We will then update the entire sub-dict in the managed coordination dict
    thread_info = {
        'type': 'results_handler',
        'phase': 'awaiting_test_timing',
        'thread_id': current_thread_id,
        'process_id': current_proc_id
    }
    coordination_dict['thread_states'][current_thread_id] = thread_info
    
    # Block until start and end times added to coordination dict
    wait_for_timings(coordination_dict)
    
    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'preparing_for_start'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Set the Start and End times
    start_time = coordination_dict['start_time']
    end_time = coordination_dict['end_time']

    # Initialise the bucket_timings and results dicts
    bucket_timings = get_bucket_timings_dict(start_time, end_time, read_config.result_bucket_duration_secs)
    results = get_init_results_dict(coordination_dict, bucket_timings)
    
    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'waiting_for_start_time'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Wait until start time
    wait_for_start(start_time)

    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'awaiting_resp_queue_items'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Block while waiting for queue items
    while response_metrics_queue.empty():
        time.sleep(0.01)
    
    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'executing'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Loop until endtime (+1s for final responses to come through) has passed and queue is empty
    while datetime.datetime.now() < (end_time + datetime.timedelta(seconds=1)) or not response_metrics_queue.empty():
        # If the queue has items
        if not response_metrics_queue.empty():
            # Get item from the queue
            response_item_batch = response_metrics_queue.get(True, 2)

            # For each item in the batch
            for response_item in response_item_batch:    
                # Assign vars for each of the elements of the tuple
                resp_reading_group, resp_response_time, resp_timestamp = response_item

                # Deterime the bucket no for the given timestamp
                bucket_no = get_bucket_no(bucket_timings, resp_timestamp)

                # Update the bucket values (by reading group and bucket) for this response_time
                results['reading_groups'][resp_reading_group]['buckets'][bucket_no] = add_resp_to_bucket(results['reading_groups'][resp_reading_group]['buckets'][bucket_no], resp_response_time)

            # Update the full results dict and then the coordination dict with the latest results
            results = update_summary_metrics(results)
            coordination_dict['results'] = results

    # Update the thread state to show thread is finished
    thread_info['phase'] = 'finished'
    coordination_dict['thread_states'][current_thread_id] = thread_info

def get_init_results_dict(coordination_dict, bucket_timings):
    results_dict = { 
        "test_run": coordination_dict["start_time"].strftime("%Y%m%d-%H%M%S"),
        "start_time": coordination_dict["start_time"].strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": coordination_dict["end_time"].strftime("%Y-%m-%d %H:%M:%S"),
        'read_procs': coordination_dict['read_procs'],
        'threads_per_read_proc': coordination_dict['threads_per_read_proc'],
        'total_read_threads': coordination_dict['read_procs'] * coordination_dict['threads_per_read_proc'],
        "test_duration_seconds": (coordination_dict["end_time"] - coordination_dict["start_time"]).seconds,
        "total_docs_retrieved": 0,
        "tps": 0,
        "avg_response_ms": 0,
        "reading_groups": {}
    }

    for reading_group in coordination_dict['reading_groups_list']:
        reading_group_results = {
            "reading_group_id": reading_group['reading_group_id'],
            "read_proportion": reading_group['read_proportion'],
            "docs_in_range": reading_group['docs_in_range'],
            "docs_lower": reading_group['docs_lower'],
            "docs_upper": reading_group['docs_upper'],
            "elapsed_seconds": 0,
            "total_docs_retrieved": 0,
            "tps": 0,
            "avg_response_ms": 0,
            "buckets": {}
        }
        for bucket_no in bucket_timings:
            reading_group_results['buckets'][bucket_no] = {
                    "reading_group_id": reading_group['reading_group_id'],
                    "bucket_no": bucket_no,
                    "bucket_start_time": bucket_timings[bucket_no]['bucket_start_time'].strftime("%H:%M:%S.%f"),
                    "bucket_end_time": bucket_timings[bucket_no]['bucket_end_time'].strftime("%H:%M:%S.%f"),
                    "bucket_duration_secs": (bucket_timings[bucket_no]['bucket_end_time'] - bucket_timings[bucket_no]['bucket_start_time']).seconds,
                    "total_docs_retrieved": 0,
                    "tps": 0,
                    "avg_response_time_ms": 0
                }

        results_dict["reading_groups"][reading_group['reading_group_id']] = reading_group_results
    
    return results_dict

def begin_query_execution_threads(response_metrics_queue, coordination_dict):
    # Initialise Thread list
    thread_list = []
    threads_per_read_proc = coordination_dict['threads_per_read_proc']
    coll = get_mongo_collection()
    
    # Add to the thread_list the number of threads defined in the config file
    for t in range(threads_per_read_proc):
        thread = Thread(target=execute_queries,args=(response_metrics_queue, coll, coordination_dict))
        thread_list.append(thread)

    # Start the threads
    for thread in thread_list:
        thread.start()

    # Join the threads (i.e. block until all threads complete)
    for thread in thread_list:
        thread.join()

def execute_queries(response_metrics_queue, coll, coordination_dict):
    # Define basic thread info
    current_proc_id = multiprocessing.current_process().pid
    current_thread_id = str(current_proc_id) + "-" + str(threading.current_thread().ident)

    # As sub-objects within multiprocessing managed dicts cannot be updated by individual field,
    # This will instantiate a dict used to represent the state of this thread
    # We will then update the entire sub-dict in the managed coordination dict
    thread_info = {
        'type': 'query_executor',
        'phase': 'awaiting_test_timing',
        'thread_id': current_thread_id,
        'process_id': current_proc_id
    }

    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Wait for start/end times to be added to the coordination_dict
    wait_for_timings(coordination_dict)
    
    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'preparing_for_start'
    coordination_dict['thread_states'][current_thread_id] = thread_info
    
    # Set the Start and End times
    start_time = coordination_dict['start_time']
    end_time = coordination_dict['end_time']
    
    # Set the size of the response metrics batches to build before adding to the queue
    response_metrics_batch_size = read_config.response_metrics_batch_size

    # Create a local copy of the reading_groups_list
    reading_groups_list = coordination_dict['reading_groups_list'].copy()

    # Initialise list which will represent the reading_groups weighted by read_proportion
    weighted_reading_group_list = get_weighted_reading_groups_list(reading_groups_list)
    
    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'waiting_for_start_time'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Wait for start time
    wait_for_start(start_time)

    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'executing'
    coordination_dict['thread_states'][current_thread_id] = thread_info

    # Initialise a list of response metrics, we submit batches of multiple response metrics
    #  to the queue in order to reduce contention/locking relating to the queue
    response_metrics_batch = []

    # Loop until endtime
    while (datetime.datetime.now() < end_time):
        # Get a doc id and reading group (based on defined proportionality)
        reading_group_id, doc_id = get_doc_id(reading_groups_list, weighted_reading_group_list)

        # Time the execution of the find command
        start = datetime.datetime.now()
        # This 'projects'away the 'blob' field to reduce network overhead, it shouldn't materially impact test results
        coll.find_one({"_id": doc_id},{"blob": 0})
        end = datetime.datetime.now()

        # Calculate the response time in milliseconds
        response_time_ms = ((end - start).total_seconds() * 1000)

        # Adda tuple entry to the response metrics batch
        response_metrics_batch.append((reading_group_id, response_time_ms, start))
        
        # If the number of entries in the batch has reached the batch size
        if len(response_metrics_batch) >= response_metrics_batch_size:
            # Add a the batch to the response_metrics_queue
            response_metrics_queue.put(response_metrics_batch)

            # Reset the batch
            response_metrics_batch = []
    
    # Now looping has complete, add any remaining response items to the queue
    if len(response_metrics_batch) > 0:
        response_metrics_queue.put(response_metrics_batch)

    # Update the reported 'phase' in the coordination_dict
    thread_info['phase'] = 'finished'
    coordination_dict['thread_states' ][current_thread_id] = thread_info

def get_mongo_collection():
    # Define mongoclient based on global_config
    client = MongoClient(global_config.mongo_uri)
    db = client[global_config.db_name]
    coll = db[global_config.coll_name]

    return coll

def wait_for_timings(coordination_dict):
    # While start and end times have not been added, sleep/loop
    while coordination_dict['start_time'] == False or coordination_dict['end_time'] == False: 
        time.sleep(0.1)

def get_bucket_timings_dict(start_time, end_time, bucket_duration_secs):
    # Initialise the dict and bucket_duration as a timedelta
    bucket_timings = {}
    bucket_duration = datetime.timedelta(seconds=bucket_duration_secs)
    
    # Add a small buffer to the test end_time as there is a small window after test end time where a request may be sent 
    # This is due to the small gap in execute_queries between `while now() < endtime` and `start = now()`
    end_time = end_time + datetime.timedelta(seconds=0.1)

    # Calculate number of buckets
    no_of_buckets = math.ceil((end_time - start_time) / bucket_duration)

    # Set start of first bucket to start of test, and end of first bucket to the lower of the start+bucketDur and the overall test end
    bucket_start_time = start_time
    bucket_end_time = min((start_time + bucket_duration), end_time)

    # Loop through the number of buckets required
    for bucket_no in range(no_of_buckets):
        # Add start and end times for each bucket to the dict
        bucket_timings[bucket_no] = {}
        bucket_timings[bucket_no]['bucket_start_time'] = bucket_start_time
        bucket_timings[bucket_no]['bucket_end_time'] = bucket_end_time

        # Increment the bucket times
        bucket_start_time += bucket_duration
        bucket_end_time = min((bucket_start_time + bucket_duration), end_time)
    
    # Return the bucket timings dict
    return bucket_timings

def get_bucket_no(bucket_timings, resp_timestamp):
    # For each bucket in the timings dict
    for bucket_no in bucket_timings:
        # If the current time stamp is within the start/end times for the bucket
        if resp_timestamp >= bucket_timings[bucket_no]['bucket_start_time'] and resp_timestamp <= bucket_timings[bucket_no]['bucket_end_time']:
            # Return the bucket number
            return bucket_no

def add_resp_to_bucket(bucket, resp_response_time):
    # Update the average, total and tps values based on latest response
    bucket['avg_response_time_ms'] = (((bucket['avg_response_time_ms'] * bucket['total_docs_retrieved']) + resp_response_time) / (bucket['total_docs_retrieved'] + 1))
    bucket['total_docs_retrieved'] += 1
    bucket['tps'] = bucket['total_docs_retrieved'] / bucket['bucket_duration_secs'] if bucket['bucket_duration_secs'] > 0 else "bucket duration <1s"

    return bucket

def wait_for_start(start_time):
    # While start and end times have not been added, sleep/loop
    while datetime.datetime.now() < start_time:
        time.sleep(0.001)

def get_weighted_reading_groups_list(reading_groups_list):
    weighted_reading_group_list = []

    # Generating this list is a little obtuse. We are essentially creating a list of many reading_group_ids, 
    # where the frequency of each ID is determined by the read proportion. This allows us to randomly
    # select a reading_group from the list while maintaining the desired proportionality
    
    # For each reading_group in the list
    for reading_group in reading_groups_list:
        # Add int(readingProportion * 1000) entries of the current reading_group to the array
        weighted_reading_group_list.extend([reading_group["reading_group_id"]] * int(reading_group["read_proportion"] * 1000))

    return weighted_reading_group_list

def get_doc_id(reading_groups_list, weighted_reading_group_list):
    # Select a group at random from the weighted list
    reading_group = random.choice(weighted_reading_group_list)

    # Define the lower and upper range boundaries for the doc IDs in that reading_group
    lower = reading_groups_list[reading_group]["docs_lower"]
    upper = reading_groups_list[reading_group]["docs_upper"]
    
    # Define the query based on randomly selecting an id in the defined range
    doc_id = random.randrange(lower, upper)

    return reading_group, str(doc_id)

def process_coordinator(response_metrics_queue, coordination_dict, read_duration_seconds):
    pre_start_buffer_secs = read_config.pre_start_buffer_secs
    curses_mode = read_config.curses_mode
    
    # +1 is for the Results Handler
    expected_num_of_threads = (coordination_dict["total_read_threads"]) + 1
    current_num_ready_threads = len(coordination_dict['thread_states'].keys())
    
    # While waiting for all processes/threads to start (incl +1 for results handler)
    while current_num_ready_threads != expected_num_of_threads:
        print("Waiting for " + str(expected_num_of_threads - current_num_ready_threads) + " of " +  str(expected_num_of_threads) + " threads to start")
        time.sleep(0.2)
        current_num_ready_threads = len(coordination_dict['thread_states'].keys())
    
    # Print confirmation that threads have started
    print(str(len(coordination_dict['thread_states'].keys())) + " of " +  str(expected_num_of_threads) + " threads started")

    # Set the start and end times for the test
    start_time = datetime.datetime.now() + datetime.timedelta(seconds=pre_start_buffer_secs)
    end_time = start_time + datetime.timedelta(seconds=read_duration_seconds)
    coordination_dict['start_time'] = start_time
    coordination_dict['end_time'] = end_time

    # Print querry execution about to begin
    print("Query execution to begin in " + str(pre_start_buffer_secs) + " seconds")

    # This function is used as a wrapper for the curses display (it's only used if curses_mode = true in read_config)
    def do_display(scr):
        printed_text = ''
        curses.use_default_colors()
        
        while not is_test_finished(coordination_dict):
            scr.clear()
            scr.addstr(str(get_thread_states_table(coordination_dict))+"\n \n")
            scr.addstr(str(get_bucket_results_table(coordination_dict)))
            printed_text += str(get_thread_states_table(coordination_dict)) + "\n"
            printed_text += str(get_bucket_results_table(coordination_dict)) + "\n \n"
            scr.refresh()
            time.sleep(1)

        scr.clear()
        scr.addstr(str(get_thread_states_table(coordination_dict))+"\n")
        scr.addstr(str(get_bucket_results_table(coordination_dict)))
        printed_text += str(get_thread_states_table(coordination_dict)) + "\n"
        printed_text += str(get_bucket_results_table(coordination_dict)) + "\n \n"
        scr.refresh()

        # Printed text is essentially a representation of all states of the screen in the loop above
        return printed_text


    if curses_mode:
        printed_text = curses.wrapper(do_display)
        print(printed_text)
    else:
        while not is_test_finished(coordination_dict):
            time.sleep(1)
            print("*******")
            print(get_thread_states_table(coordination_dict))
            print()
            print(get_bucket_results_table(coordination_dict))
            print("*******")

    # Get and print the results tables
    results_table = get_final_results_table(coordination_dict['results'])
    print(results_table)

    # Write the fullResultsDict to a file
    results_file_name = coordination_dict["results"]["test_run"] + "-results.json"
    write_string_to_file(json.dumps(coordination_dict['results'],indent=2), results_file_name)
    
    # Write the resultsTable to a file
    results_table_file_name = coordination_dict["results"]["test_run"] + "-results_table.txt"
    write_string_to_file(str(results_table), results_table_file_name)

    # Print file name/location on screen
    print("Results Dict written to " + results_file_name)
    print("Results Table written to " + results_table_file_name)
    
def is_test_finished(coordination_dict):
    # For each thread recording a state
    for thread_state in coordination_dict['thread_states'].values():
        # If the thread is not in the finished phase
        if thread_state['phase'] != 'finished':
            # The test is not finished
            return False
    
    # If all threads are in finished phase, test is finished
    return True

def get_thread_states_table(coordination_dict):
    table = PrettyTable()
    table.title = "Thread States " + datetime.datetime.now().strftime("%H:%M:%S.%f")
    fields = []
    rows = []

    # For each thread in the dict
    for thread_state in coordination_dict['thread_states'].values():
        # If fields have not yet been set
        if len(fields) == 0:
            # Set fields
            fields = thread_state.keys()
        
        # Initialise a new row
        row = []

        # Add values to the row
        for field in fields:
            row.append(thread_state[field])
        
        # Add the row to the table
        table.add_row(row)

    # Set the field names based on the unique fields in the fields list
    table.field_names = fields

    return table

def get_bucket_results_table(coordination_dict):
    results = coordination_dict['results']
    
    table = PrettyTable()
    
    fields = []

    if 'reading_groups' in results:
        for reading_group_no in results['reading_groups']:
            for bucket_no in results['reading_groups'][reading_group_no]['buckets']:
                bucket = results['reading_groups'][reading_group_no]['buckets'][bucket_no]

                # Set the fields            
                fields = bucket.keys()

                # Initialise a new row
                row = []

                # Add values to the row
                for field in fields:
                    row.append(bucket[field])
            
                # Add the row to the table
                table.add_row(row)

        # Set the field names based on the unique fields in the fields list
        table.field_names = fields
        table.title = "Interim Results " + datetime.datetime.now().strftime("%H:%M:%S.%f")

        return table
    else:
        return "No reading_groups yet added to results in the coordination_dict"

def get_final_results_table(results):
    outer_table = PrettyTable([str("Results for Test Run: " + results["test_run"])])
    outer_table.align = 'l'

    outer_table.add_row([get_summary_table(results)])
    outer_table.add_row([get_reading_groups_table(results)])
    outer_table.add_row([get_buckets_table(results)])

    return outer_table

def get_summary_table(results):
    fields = []
    row = []
    start_time = results.pop('start_time')
    end_time = results.pop('end_time')

    for key,value in results.items():
        if key != "reading_groups":
            fields.append(key)
            row.append(value)
    
    summary_table = PrettyTable(fields)
    summary_table.title = "Results Summary (" + start_time + " - " + end_time + ")"
    summary_table.add_row(row)

    return summary_table

def get_reading_groups_table(results):
    fields = []
    rows = []

    for reading_group_id in results["reading_groups"]:
        reading_group = results["reading_groups"][reading_group_id]
        if len(fields) == 0:
            for key in reading_group.keys():
                if key != "buckets":
                    fields.append(key)
        
        row = []

        for field in fields:
            if field != "buckets":
                row.append(reading_group[field])

        rows.append(row)

    reading_group_table = PrettyTable(fields)
    reading_group_table.title = "Reading Group Results"
    
    for row in rows:
        reading_group_table.add_row(row)

    return reading_group_table

def get_buckets_table(results):
    fields = []
    rows = []

    for reading_group_id in results["reading_groups"]:
        reading_group = results["reading_groups"][reading_group_id]
        for bucket_no in reading_group["buckets"]:
            bucket = reading_group["buckets"][bucket_no]
            if len(fields) == 0:
                fields = bucket.keys()
            
            row = []

            for field in fields:
                row.append(bucket[field])
            
            rows.append(row)
    
    buckets_table = PrettyTable(fields)
    buckets_table.title = "Bucket Results"

    for row in rows:
        buckets_table.add_row(row)
    
    return buckets_table

def update_summary_metrics(results):
    new_results = results

    full_test_duration_seconds = results["test_duration_seconds"]
    full_test_total_docs_retrieved = 0
    full_test_total_response_time_ms = 0
        
    for reading_group in results["reading_groups"]:
        reading_group_duration_seconds = 0
        reading_group_total_docs_retrieved = 0
        reading_group_total_response_time_ms = 0

        for bucket_no in results["reading_groups"][reading_group]["buckets"]:
            bucket = results["reading_groups"][reading_group]["buckets"][bucket_no]

            reading_group_duration_seconds += bucket["bucket_duration_secs"]
            reading_group_total_docs_retrieved += bucket["total_docs_retrieved"]
            reading_group_total_response_time_ms += ( bucket["avg_response_time_ms"] * bucket["total_docs_retrieved"] )
        
        results["reading_groups"][reading_group]["elapsed_seconds"] = reading_group_duration_seconds
        results["reading_groups"][reading_group]["total_docs_retrieved"] = reading_group_total_docs_retrieved
        results["reading_groups"][reading_group]["tps"] = reading_group_total_docs_retrieved / reading_group_duration_seconds if reading_group_duration_seconds > 0 else 0
        results["reading_groups"][reading_group]["avg_response_ms"] = reading_group_total_response_time_ms / reading_group_total_docs_retrieved if reading_group_total_docs_retrieved > 0 else 0

        full_test_total_docs_retrieved += reading_group_total_docs_retrieved
        full_test_total_response_time_ms += reading_group_total_response_time_ms
    
    results["total_docs_retrieved"] = full_test_total_docs_retrieved
    results["tps"] = full_test_total_docs_retrieved / full_test_duration_seconds if full_test_duration_seconds > 0 else 0 
    results["avg_response_ms"] = full_test_total_response_time_ms / full_test_total_docs_retrieved if full_test_total_docs_retrieved > 0 else 0

    return results

def write_string_to_file(string, file_name):
    path = "./read_results/"
    if not os.path.exists(path):
        os.mkdir(path)

    full_file_path = path + file_name

    with open(full_file_path, 'w') as file:
        file.write(string)

def join_processes(process_list):
    for process in process_list:
        process.join()

    print("All processes joined")

if __name__ == "__main__":
    main()