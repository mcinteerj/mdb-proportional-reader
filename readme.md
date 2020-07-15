# Proportional Reader
## Purpose
This tool was creator in order to make it easier to test and/or demonstrate the impacts of having a 'working set' cached in memory on overall throughput and response time from MongoDB. 

The working set is the set of regularly accessed data. It is generally made up of a combination of indexes as well as the most frequently accessed documents within the database. 

Where possible, the working set should be of a size which can be held within the memory of the MongoDB server, as this allows many 'find' requests to be served from memory rather than from disk. When serving records from memory (WiredTiger cache), MongoDB will have a lower response time and achieve higher throughput metrics when compared to serving records from disk.

## Requirements/Dependencies

TBC.

You should be able work this out using trial and error, I'd recommend installing PTable rather than PrettyTable for nicer result printing. 

## Configuration
The configuration of the tool is contained in three files:
* ./global_config.py -> Contains the MongoDB connection information and database/collection names
* ./generate_config.py -> Contains the generation workload configuration
* ./read_config.py -> Contains the read workload configuration

The settings/values in these files are documented in detail in the sections below. The key values you are likely to want to update when running a test are:

```sh
./global_config.py
    mongo_uri

./generate_config.py
    docs_to_insert
    processes

./read_config.py
    read_ratio_list
    docs_ratio_list
    read_duration_seconds
    read_procs
    threads
```

## Generate Data
To execute the generator, run:
```sh
python3 ./generator.py
```

Interim results will be printed to screen throughout the test run, and final results will be printed at the completion of the test. 

The results will also be written in both json and a text/table format to files in the `./generate_results/` directory.

## Read Data
To execute the reader, run:
```sh
python3 ./read_data.py
```

Interim results will be printed to screen throughout the test run, and final results will be printed at the completion of the test. 

The results will also be written in both json and a text/table format to files in the `./read_results/` directory.

# Detailed Documentation
## Data Generation/Insertion
The `./generator.py` script will automatically generate the number of documents specified in the `/generate_config.py` file and insert these into the specified MongoDB cluster. Each document is configured to have the following shape (as defined in function `create_document()`):
```json
{
    "_id": 1,
    "id": 1,
    "proc": "3767-123145490526208",
    "blob": BinData(0,"udDNAG...")
}
```

The `_id` and `id` will always have the same value. It is a monotonically increasing integer value, beginning at `0` for the first document and increasing up to the total number of documents to be inserted. 

Having these two fields was done in order to have two identical fields used for querying data, where one would automatically be indexed, and one would not - making it easy to configure a read workload to contrast the difference between querying an indexed field as opposed to an unindexed field. 

The `proc` field is the process and thread number of the thread which inserts the document. This was useful during debugging, but serves no functional purpose.

The `blob` field is a randomly generated 240 byte binary value. This is included to increase the overall size of the data set, as well as to ensure a more realistic compression rate than if using the same blob value in every document. 

Each document should (on average) be approximately 300B in size. I have observed a compression ratio of ~2.5:1 based on this document size/shape. 

### Generate Config
The generation config is defined in the `generate_config.py` file. Key configuration options are described below:


#### Total Number of Docs
The total number of documents to be generated and inserted is defined by the `docs_to_insert` value. 

#### Insert Chunk Size
Documents are inserted leveraging `insert_many()` meaning they are sent to MongoDB in batches. The batch size is defined by the `insert_chunk_size` value. A larger chunk size will increase throughput, but there is a trade-off where the chunks get suitably large and cause a lot of variability in performance. 

#### Processes/Threads Per Process
The 'effort' of generating and inserting the number of documents defined by `docs_to_insert` is split between the number of processes and threads defined in the `processes` and `threads_per_process` values.

In most cases, 1-2 threads per process will be optimal, however more threads may be useful in situations with higher network latency or other situations where an individual thread may be 'waiting' for a response. 

#### Reporting Interval
While the script is executing, interim results will be printed to stdout periodically. The time between printing interim results is based on the `reporting_interval` value.

#### Result Buckets
The results are collated into buckets in order to be able to see if/how performance changes throughout the test. The duration of these buckets is defined by `result_bucket_duration`.

#### Response Metrics Batches
In order to isolate the generation/insertion processes from the expense of calculating and reporting of results, the generation/insertion processes will put response metrics on a queue. Due to the highly concurrent nature of the workload, there is a need to batch response metrics when adding them to the queue (i.e. reduce the likelihood that two processes attempt to write to the queue simultaneously). The `response_metrics_batch_size` value controls the size of batches added to the response metrics queue. 

## Reading Data
The `read_data.py` script will spawn a number of processes and threads which will query documents in a MongoDB cluster as fast as they can. 

The reading functionality assumes documents exist in the defined collection and that those documents have the shape specified by the generation component. 

For each read request, the script will select a document ID to be used for the query. The script is constructed in a way which allows the user to 'skew' the read workload in order to make it more likely that IDs for certain portions of the documents are more likely to be selected.

This is intended to represent the fact that 'real' workloads will often have documents that are 'warmer' (more frequently accessed) than other documents - for example because some end-users a more active than others.

### Read Config
The read config is defined in the `read_config.py` file. Key configuration options are described below:

#### Read and Document Ratios
The way the read workload is skewed towards certain documents is controlled by the `read_ratio_list` and `docs_ratio_list` values. The values are arrays which are used to construct 'reading groups' which then dictate how the read processes will query documents.

For example:
```py
read_ratio_list = [3,2]
docs_ratio_list = [2,8]
```
The first item of each list constructs the first reading group, the second value would construct the next reading group and so on. There is no defined limit to the number of groups.

The first items of the list above would result in a reading group which targeted 60% of the read workload at 20% of the documents. 60% is calculated by `3/sum(read_ratio_list)`, likewise 20% is calculated as `2/sum(docs_ratio_list)`. In this case the sum of read_ratio_list is 5 and the docs_ratio_list is 10.

Each list could be specified as a single integer array value, which would result in 100% of the read workload randomly targeting 100% of the documents in the collection (i.e. no skew, completely random reads). 

The script has been tested with as many as 18 reading groups.

#### Read Duration
The length of time the read workload will run for is specified by `read_duration_seconds`. It is recommended to run test for multiple minutes at a minimum in order to ensure that the cache is warmed for the majority of the test, and that any 'burstiness' relating to underlying infrastructure is exhausted (e.g. EC2 burstable IOPS/CPU).

#### Result Bucket Duration
In order to show how performance changes throughout a test, results are grouped into buckets. The duration of each bucket is controlled by `result_bucket_duration_secs`. 

A value of between 5% and 30% of the overall test duration is a reasonable bucket length. Shorter values will give you more granularity (which may be useful), but also creates a lot more information to print/report (this shouldn't be a performance issue, but rather becomes 'noisy' to interpret).

#### Read Processes/Threads
The script will generate the defined number of processes, which will in turn generate the defined number of threads in order to execute the read workload.

Keep in mind, python will allow you to specify more processes than you may have cores available - in this case, you will not get additional processing power, but rather the processes will just be swapped in and out. So make sure your host machine is powerful enough to generate the amount of load you desire. 

#### Curses Mode
Curses mode is an alternate way of reporting interim results that 'displays' the interim results on the terminal, rather than printing them to stdout. This can be a tidier/nicer way to see interim results.

#### Pre Start Buffer
As the script leverages multiple discrete processes, there is a need to wait for all processes to spawn and become ready to begin the test. The `pre_start_buffer_secs` is the length of time between when all processes become 'ready' and when the test actually starts. There should be no need to change this value.

#### Response Metrics
In order to isolate the read processes from the expense of calculating and reporting of results, the read processes will put response metrics on a queue. 

Due to the highly concurrent nature of the workload, there is a need to batch response metrics when adding them to the queue (i.e. reduce the likelihood that two processes attempt to write to the queue simultaneously). The `response_metrics_batch_size` value controls the size of batches added to the response metrics queue. 

## To-do List
* Update results dict fields to use datetime (rather than str)
* Update results dict fields to use reasonable and consistent rounding
* Add some kind of -p option which just prints the reading groups/config but doesn't execution any actual workload

## Future Work
* Look at using a scheduler or similar to start the execution (rather than while less than loop)
* Look at using 'pools' to do the query execution
* Consider making the response batch size dynamic based on throughput or similar
    - Bigger batches help results_handler throughput, however if response times are high, it may take longer to fill a batch and therefore interim reporting will not be accurate
* Consider using command line arguments to drive config