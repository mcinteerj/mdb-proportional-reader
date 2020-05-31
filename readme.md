# Proportional Reader

## Purpose

TBC

## How it works

TBC

## Things to do

### Should do now
### Things Remaining

[ ] Check how the new response queue batch process works under higher load (on GCP VM). Run test cases such as
    - Normal test, batch size [1,200]
    - Test with 0.01s sleep in each execution, batch size [1,200]
    - Run the two test above with 1:1 proc:thread, and then with 10:1 proc:thread
[ ] Review comments to make sure they all still make sense
[ ] Compare to POCDriver for a similar number of threads
[ ] Run a couple of proper tests
[ ] Write up a readme.md


#### Can do later
[ ] Use a scheduler or similar to start the execution (rather than while less than loop)
[ ] The interim results printing seems to lag behind the actual time, I think the resultsHandler is falling behind. May be worth considering how to improve it's perf. Possibly tuples over dicts/lists.
[ ] Do some quick analysis on how much execution workload could overload the response handling workload (if realistic at all)... some back pressure isn't an issue however the queue will fill at 30k
    - consider using less precision in response time to help with this (averages over thousands of precise decimals is probably killing you)
    - consider moving the responsetime calculation (i.e. (end - start).totalsecs) from the query execution into the results handler (less work for query exec to do)
[ ] Fix bucket reporting. It is currently incorrect due to the introduction of bucketing. Some requests will be out of order as they are no longer being added to the queue one by one but rather in batches by each processes, each batch will overlap and the 'last response time' of one batch may well be ahead of the last response times of another adjacent batch.
[ ] Test edge cases relating to bucket duration > test time
[ ] Look at using 'pools' to do the multiprocessing