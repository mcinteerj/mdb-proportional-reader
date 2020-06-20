# Proportional Reader
## Purpose
This tool was creator in order to make it easier to test and/or demonstrate the impacts of having a 'working set' in memory on overall throughput and response time from MongoDB. 

The working set is the set of regularly accessed data and is generally a combination of indexes and the most frequently accessed documents within the database. Where possible, the working set should be of a size which can be held within the memory of the MongoDB server, as this allows many 'find' requests to be served from memory rather than from disk. When serving records from memory (WiredTiger cache), MongoDB will have a lower response time and achieve higher throughput metrics when compared to serving records from RAM.

## How it works
### Generating Data

### Reading Data

## Usage
### Config Files
The configuration of the tool is contained in three files:
* ./global_config.py -> Contains the MongoDB connection information
* ./generate_config.py -> Contains the generation workload configuration
* ./read_config.py -> Contains the read workload configuration

### Generating Data

### Reading Data

## Future work
### Immediate Generation Activities
[ ] Implement threading
[ ] Test Insert Many with 1 doc vs Insert One

### Future
[ ] Look at using a scheduler or similar to start the execution (rather than while less than loop)
[ ] Look at using 'pools (mulitprocessing)' to do the query execution
[ ] Consider making the response batch size dynamic based on throughput or similar
    - Bigger batches help results_handler throughput, however if response times are high, it may take longer to fill a batch and therefore interim reporting will not be accurate
[ ] Consider using command line arguments to drive config