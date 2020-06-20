#!/usr/bin/env python3
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
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
import generate_config
import sys
import curses

def main():
    # Retrieve config
    print("Retrieving config from file...")
    reporting_interval = generate_config.reporting_interval
    
    # Create a multi-proc manager to manage a shared dictionary between processes
    manager = multiprocessing.Manager()

    # Create a managed/shared dict 
    coordination_dict = manager.dict({
        "test_run": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'start_time': False,
        'end_time': False,
        'duration_secs': False,
        'docs_to_insert': generate_config.docs_to_insert,
        'no_of_processes': generate_config.processes,
        'threads_per_process': generate_config.threads_per_process,
        'insert_chunk_size': generate_config.insert_chunk_size,
        'process_states': manager.dict(),
        'result_buckets': manager.dict(),
        'docs_inserted': 0,
        'docs_inserted_per_second': 0,
        'no_of_responses': 0,
        'avg_response_time_ms': 0
    })

    # Create a queue for each process to add response metrics results to
    response_metrics_queue = multiprocessing.Queue()

    process_list = get_process_list(coordination_dict, response_metrics_queue)

    drop_collection(get_mongo_collection())

    start_processes(process_list)

    process_coordinator(coordination_dict, response_metrics_queue)

    join_processes(process_list)

def get_process_list(coordination_dict, response_metrics_queue):
    process_list = []
    lower_doc_id = 0
    docs_per_process = math.floor(coordination_dict['docs_to_insert'] / coordination_dict['no_of_processes'])
    upper_doc_id = lower_doc_id + docs_per_process

    # Add the results handler process
    process_list.append(multiprocessing.Process(target=results_handler,args=(coordination_dict, response_metrics_queue)))

    print()
    print("Creating Insert Processes")
    print()

    for p in range(coordination_dict['no_of_processes']):
        # Add process to the list
        process_list.append(multiprocessing.Process(target=insert_many_documents,args=(lower_doc_id, upper_doc_id, coordination_dict, response_metrics_queue)))

        print("Process " + str(p) + " inserting docs " + str(lower_doc_id) + " - " + str(upper_doc_id))

        # Increment doc_id counters
        lower_doc_id = upper_doc_id
        upper_doc_id = lower_doc_id + docs_per_process

        # If upper is above the total number of docs to insert, cap it at total docs to insert
        if upper_doc_id + docs_per_process > coordination_dict['docs_to_insert']:
            upper_doc_id = coordination_dict['docs_to_insert']

    return process_list

def start_processes(process_list):
    # Start each process in the list
    for process in process_list:
        process.start()

def insert_many_documents(lower_doc_id, upper_doc_id, coordination_dict, response_metrics_queue):
    current_proc_id = multiprocessing.current_process().pid
    
    current_doc_id = lower_doc_id
    insert_chunk_size = generate_config.insert_chunk_size
    
    collection = get_mongo_collection()
    
    update_process_state(coordination_dict, 'doc_inserter', 'awaiting_timing', current_proc_id)

    # Wait for start time to be provided
    while not coordination_dict['start_time']:
        time.sleep(0.1)

    update_process_state(coordination_dict, 'doc_inserter', 'awaiting_start', current_proc_id)

    # Wait for start time
    while datetime.datetime.now() < coordination_dict['start_time']:
        time.sleep(0.01)

    update_process_state(coordination_dict, 'doc_inserter', 'inserting', current_proc_id)

    response_metrics_batch = []

    while current_doc_id < upper_doc_id:
        chunk_upper_doc_id = min(upper_doc_id, current_doc_id + insert_chunk_size)
        docs_list = []

        while current_doc_id < chunk_upper_doc_id:
            docs_list.append(create_document(current_doc_id, current_proc_id))

            current_doc_id += 1
        
        start = datetime.datetime.now()
        collection.insert_many(docs_list)
        end = datetime.datetime.now()

        response_time_ms = ((end - start).total_seconds() * 1000)
        response_metrics_batch.append((start, response_time_ms, len(docs_list)))

        # If response metrics batch has reached batch size, or this is the last document, add metrics to queue
        if len(response_metrics_batch) > generate_config.response_metrics_batch_size or current_doc_id == upper_doc_id:
            response_metrics_queue.put(response_metrics_batch)
            response_metrics_batch = []

    update_process_state(coordination_dict, 'doc_inserter', 'complete', current_proc_id)

    return

def create_document(current_doc_id, process_id):
    doc = {
        "_id": current_doc_id,
        "id": current_doc_id,
        "proc": process_id
    }
    
    return doc

def process_coordinator(coordination_dict, response_metrics_queue):
    expected_no_of_processes = coordination_dict['no_of_processes'] + 1 # +1 for results handler proc
    current_no_of_processes = 0
    pre_start_buffer_secs = 1

    while current_no_of_processes < expected_no_of_processes:
        print()
        print("Waiting for " + str(expected_no_of_processes) + " processes to start (currently: " + str(current_no_of_processes) + " started)")
        time.sleep(0.5)
        current_no_of_processes = len(coordination_dict['process_states'].keys())
    
    print()    
    print("All processes started")

    coordination_dict['start_time'] = datetime.datetime.now() + datetime.timedelta(seconds=pre_start_buffer_secs)
    coordination_dict['end_time'] = coordination_dict['start_time']

    while coordination_dict['docs_inserted'] < coordination_dict['docs_to_insert']:
        print(get_interim_results(coordination_dict, "Interim Results " + datetime.datetime.now().strftime("%H:%M:%S.%f")))
        time.sleep(generate_config.reporting_interval)

    results_table = get_final_results(coordination_dict)
    print(results_table)


    # Write the results_table to a file
    results_table_file_name = coordination_dict["test_run"] + "-results_table.txt"
    write_string_to_file(str(results_table), results_table_file_name)

    # Write the full dict to a file
    results_dict_file_name = coordination_dict["test_run"] + "-results.json"
    write_string_to_file(json.dumps(coordination_dict.copy(), indent=2, default=str), results_dict_file_name)

    return

def get_interim_results(coordination_dict, title):
    result_buckets = coordination_dict['result_buckets'].copy()
    
    table = PrettyTable()
    table.title = title
    
    if len(result_buckets.keys()) == 0:
        return("\nNo interim results calculated yet.")
        

    fields = []
    fields.extend(result_buckets[0].keys())
    table.field_names = fields

    for bucket in result_buckets:
        table.add_row(result_buckets[bucket].values())

    return table

def get_summary_results(coordination_dict):
    start_time = coordination_dict.pop('start_time')
    end_time = coordination_dict.pop('end_time')
    fields = ['duration_secs', 'no_of_processes', 'threads_per_process', 'insert_chunk_size', 'docs_inserted', 'docs_inserted_per_second', 'no_of_responses', 'avg_response_time_ms']
    
    summary_table = PrettyTable(fields)
    summary_table.title = "Results Summary (" + str(start_time) + " - " + str(end_time) + ")"
    
    row = []

    for field in fields:
        row.append(coordination_dict[field])
    
    
    summary_table.add_row(row)

    return summary_table

def get_final_results(coordination_dict):
    outer_table = PrettyTable([str("Results for Test Run: " + coordination_dict["test_run"])])
    outer_table.align = 'l'

    outer_table.add_row([get_summary_results(coordination_dict)])
    outer_table.add_row([get_interim_results(coordination_dict, "Results Breakdown " + datetime.datetime.now().strftime("%H:%M:%S.%f"))])

    return outer_table

def update_process_state(coordination_dict, type, phase, current_proc_id):
    coordination_dict['process_states'][current_proc_id] = {
        'type': type,
        'phase': phase,
        'process_id': current_proc_id
    }

def results_handler(coordination_dict, response_metrics_queue):
    current_proc_id = multiprocessing.current_process().pid
    update_process_state(coordination_dict, 'results_handler', 'awaiting_timing', current_proc_id)

    # Wait for start time to be provided
    while not coordination_dict['start_time']:
        time.sleep(0.1)
    
    update_process_state(coordination_dict, 'results_handler', 'preparing_for_start', current_proc_id)

    # Set the Start and End times
    start_time = coordination_dict['start_time']
    end_time = datetime.datetime.min

    update_process_state(coordination_dict, 'results_handler', 'awaiting_response_items', current_proc_id)
    
    while response_metrics_queue.empty():
        time.sleep(0.1)

    update_process_state(coordination_dict, 'results_handler', 'executing', current_proc_id)
    
    while coordination_dict['docs_inserted'] < coordination_dict['docs_to_insert'] or not response_metrics_queue.empty():
        if not response_metrics_queue.empty():
            resp_item_list = response_metrics_queue.get()

            for timestamp, response_time_ms, no_of_docs in resp_item_list:
                update_results(coordination_dict, timestamp, response_time_ms, no_of_docs)
                end_time = max(end_time, timestamp)

            update_summary_results(coordination_dict, end_time)
    
    # Tidy up the last bucket (by updating end-time to match end-time of the test and re-calculating the TPS)
    update_last_bucket(coordination_dict)

    update_process_state(coordination_dict, 'results_handler', 'complete', current_proc_id)

    return

def update_summary_results(coordination_dict, end_time):
    coordination_dict['end_time'] = end_time
    coordination_dict['duration_secs'] = (end_time - coordination_dict['start_time']).total_seconds()

    total_response_time = 0
    docs_inserted = 0
    no_of_responses = 0


    for bucket in coordination_dict['result_buckets']:
        docs_inserted += coordination_dict['result_buckets'][bucket]['docs_inserted']
        no_of_responses += coordination_dict['result_buckets'][bucket]['no_of_responses']
        total_response_time += (coordination_dict['result_buckets'][bucket]['avg_response_time_ms'] * coordination_dict['result_buckets'][bucket]['docs_inserted'])
    

    coordination_dict['docs_inserted'] = docs_inserted
    coordination_dict['no_of_responses'] = no_of_responses
    coordination_dict['docs_inserted_per_second'] = docs_inserted / coordination_dict['duration_secs']
    coordination_dict['avg_response_time_ms'] = total_response_time / coordination_dict['docs_inserted']

def update_results(coordination_dict, timestamp, response_time_ms, no_of_docs):
    bucket_no = get_bucket_no(coordination_dict, timestamp)
    result_buckets = coordination_dict['result_buckets'].copy()

    if bucket_no not in result_buckets:
        result_buckets[bucket_no] = {
            'bucket_start_time': coordination_dict['start_time'] + datetime.timedelta(seconds=( generate_config.result_bucket_duration * bucket_no )), 
            'bucket_end_time': coordination_dict['start_time'] + datetime.timedelta(seconds=( generate_config.result_bucket_duration * ( bucket_no + 1 ))),
            'docs_inserted': 0,
            'docs_inserted_per_second': 0,
            'no_of_responses': 0,
            'avg_response_time_ms': 0
        }
    
    result_buckets[bucket_no]['avg_response_time_ms'] = (((result_buckets[bucket_no]['avg_response_time_ms'] * result_buckets[bucket_no]['no_of_responses']) + response_time_ms) / (result_buckets[bucket_no]['no_of_responses'] + 1))
    result_buckets[bucket_no]['no_of_responses'] += 1
    result_buckets[bucket_no]['docs_inserted'] += no_of_docs
    result_buckets[bucket_no]['docs_inserted_per_second'] = result_buckets[bucket_no]['docs_inserted'] / generate_config.result_bucket_duration

    coordination_dict['result_buckets'] = result_buckets

def update_last_bucket(coordination_dict):
    bucket_no = get_bucket_no(coordination_dict, coordination_dict['end_time'])
    result_buckets = coordination_dict['result_buckets'].copy()

    result_buckets[bucket_no]['bucket_end_time'] = coordination_dict['end_time']
    result_buckets[bucket_no]['docs_inserted_per_second'] = result_buckets[bucket_no]['docs_inserted'] / (result_buckets[bucket_no]['bucket_end_time'] - result_buckets[bucket_no]['bucket_start_time']).total_seconds()

    coordination_dict['result_buckets'] = result_buckets

def get_bucket_no(coordination_dict, timestamp):
    time_since_start = timestamp - coordination_dict['start_time']
    bucket_no = math.floor(time_since_start.total_seconds() / generate_config.result_bucket_duration)

    return bucket_no
    
def docs_still_inserting(coordination_dict):

    process_states = coordination_dict['process_states'].copy()

    for process in process_states:
        if process_states[process]['phase'] != "complete":
            return True
    
    return False

def get_mongo_collection():
    # Define mongoclient based on global_config
    client = MongoClient(global_config.mongo_uri)
    db = client[global_config.db_name]
    coll = db[global_config.coll_name]

    return coll

def drop_collection(coll):
    coll.drop()

def write_string_to_file(string, file_name):
    path = "./generate_results/"
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