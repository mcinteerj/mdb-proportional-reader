# Proportional Reader

## Purpose

TBC

## How it works

TBC

## Things to do

### Should do now
### Things Remaining
[ ] Review comments to make sure they all still make sense
[ ] Compare to POCDriver for a similar number of threads
[ ] Run a couple of proper tests
[ ] Write up a readme.md
[ ] The results handler is 'missing' the final batch of results inbound from the execution threads. I think this is because they arrive after the end time and the results handler has already broken the loop. Extending the loop by adding 2s to the end time in the results handler allowed it to see the additional responses, but it cause an issue with bucketing as it created a new bucket for every record (as each one met the curren time stamp > end time stamp)
        - Probably best to move back to defining the buckets rigidly at the start of the results handling and then just add each result into the relevant bucket as you go. 
        - You could update the bucket summaries with each response item as opposed to doing it once the bucket is finalised. This is probably a fair bit more work for the results handler (consider number precision...), but seems like it might the only way to provide _some_ reporting during the test. The alternative is to just wait till the end then do a bulk summary.
[ ] Check how the new response queue batch process works under higher load (on GCP VM). Run test cases such as
    - Normal test, batch size [1,200]
    - Test with 0.01s sleep in each execution, batch size [1,200]
    - Run the two test above with 1:1 proc:thread, and then with 10:1 proc:thread

#### Can do later
[ ] Use a scheduler or similar to start the execution (rather than while less than loop)
[ ] The interim results printing seems to lag behind the actual time, I think the resultsHandler is falling behind. May be worth considering how to improve it's perf. Possibly tuples over dicts/lists.
[ ] Do some quick analysis on how much execution workload could overload the response handling workload (if realistic at all)... some back pressure isn't an issue however the queue will fill at 30k
    - consider using less precision in response time to help with this (averages over thousands of precise decimals is probably killing you)
    - consider moving the responsetime calculation (i.e. (end - start).totalsecs) from the query execution into the results handler (less work for query exec to do)
[ ] Fix bucket reporting. It is currently incorrect due to the introduction of bucketing. Some requests will be out of order as they are no longer being added to the queue one by one but rather in batches by each processes, each batch will overlap and the 'last response time' of one batch may well be ahead of the last response times of another adjacent batch.
[ ] Test edge cases relating to bucket duration > test time
[ ] Look at using 'pools' to do the multiprocessing