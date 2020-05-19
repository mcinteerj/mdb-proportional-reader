#!/usr/bin/env python3
from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from multiprocessing import Process, Queue
from timeit import default_timer as timer
import time
import math
import json
import os, sys
import global_config
import generate_config

def main():
    # Drop the existing collection if it exists
    dropCollection()
    
    # Initialise variables based on config
    processes = generate_config.processes
    docsToGenerate = generate_config.docsToGenerate
    increment = math.floor(docsToGenerate / processes)

    count = 0
    processesDict = {}
    processList = []

    # Create a queue to track progress
    progressQueue = Queue()
    
    # For each process
    for p in range(processes):
        # If we aren't in the final loop
        if ( count <= (docsToGenerate - (2 * increment)) ):
            # Set lower/upper appropriately
            lower = count
            upper = count + increment

        else:
            # Set lower to count and upper to total num of docs to generate
            lower = count
            upper = docsToGenerate
        
        # Add the lower/upper to the processes dict
        processesDict[p] = {"lower": lower, "upper": upper}
        
        # Define the process and add it to the list
        process = Process(target=insertMany,args=(lower, upper, p, progressQueue))
        processList.append(process)
        
        # Increment the counter
        count += increment
        
    # Print the processDict
    print(json.dumps(processesDict,indent=4))

    startReadProcesses(processList)
    
    # Initiate progress monitor
    progressMonitor(progressQueue, processes, docsToGenerate)
    
    joinReadProcesses(processList)

def dropCollection():
    coll = getMongoCollection()
    coll.drop()

def getMongoCollection():
    # Define mongoclient based on global_config
    client = MongoClient(global_config.mongo_uri)
    db = client[global_config.dbname]
    coll = db[global_config.collname]

    return coll

def startReadProcesses(processList):
    try:
        # Start each process in the list
        for process in processList:
            process.start()
    except: 
        print("Error executing processes in processList")

def joinReadProcesses(processList):
    try:
        # Start each process in the list
        for process in processList:
            process.join()
    except: 
        print("Error joining processes in processList")

def insertMany(lower, upper, proc, progressQueue):
    print("Processs " + str(proc) + " starting.")

    coll = getMongoCollection()

    # Initialise variables
    maxChunkSize = generate_config.maxGenerateChunkSize
    chunk = maxChunkSize
    count = 0
    
    # Notify progressQueue proc is starting
    progressQueue.put({
        "type": "start",
        "proc": proc
    })

    # While we haven't inserted all docs
    while (count < (upper - lower)):
        # Reset docsArray
        docsArray = []
        
        # Set chunk appropriately based on if this is last chunk or not
        if ((upper - (lower + count)) > maxChunkSize):
            chunk = maxChunkSize
        else:
            chunk = (upper - (lower + count))
        
        # For each doc in chunk, generate the doc and add to array
        for i in range(chunk):
            docsArray.append(generateDocument((lower + count + i), proc))

        # Increment the count by chunk size
        count += chunk
        
        # Send the increment to the progressQueue to enable progress tracking)
        progressQueue.put({
            "type": "chunk",
            "proc": proc,
            "chunk": chunk
        })

        # Insert all the generated docs
        coll.insert_many(docsArray)
    
    # Notify progressQueue proc is stopping
    progressQueue.put({
        "type": "stop",
        "proc": proc
    })

def generateDocument(id, proc):
    doc = {
        "_id": id,
        "id": id, 
        "proc": proc 
        #"blob": os.urandom(500)
        }
    return doc

def progressMonitor(progressQueue, noOfProcs, docsToGenerate):
    monitorRunning = True
    runningProcesses = []
    docsGenerated = 0
    progress = 0
    reportingInterval = generate_config.reportingIntervalSeconds
    nextReport = 0
    startTime = timer()


    while monitorRunning:
        # Pull item from Queue
        item = progressQueue.get(True, 2)
        
        # Print progress update at interval
        now = timer()
        if (now - startTime > nextReport):
            print(str(round(progress * 100,2)) + "% of documents generated/inserted (" + str(docsGenerated) + "/" + str(docsToGenerate) + ") after " + str(int(now - startTime)) + " seconds" )
            nextReport += reportingInterval

        # If item type is start, add pid to runningProcesses list
        if item["type"] == "start":
            runningProcesses.append(item["proc"])
            print("Start item found in queue for pid: " + str(item["proc"]))
        # Else if item type is stop, remove pid from runningProcesses list

        elif item["type"] =="stop":
            runningProcesses.remove(item["proc"])
            print("Stop item found in queue for pid: " + str(item["proc"]))
            
            # If runningProcesses has zero items, stop the monitor
            # Note: this if statement only triggers when the item type is stop, meaning it won't be triggered before processes have started
            if len(runningProcesses) == 0:
                monitorRunning = False
                now = timer()
                print(str(round(progress * 100,2)) + "% of documents generated/inserted (" + str(docsGenerated) + "/" + str(docsToGenerate) + ") after " + str(round(now - startTime,2)) + " seconds" )

        # Else if item type is chunk, add it to docs generated
        elif item["type"] == "chunk":
            docsGenerated += item["chunk"]
            progress = docsGenerated / docsToGenerate
        else:
            sys.exit("Item added to progressQueue that doesn't match expected format")

if __name__ == "__main__":
    main()