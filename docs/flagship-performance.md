# Flagship measurements

Measured on this Windows machine at 2026-09-10 18:09 UTC with Node 24.19.0 and Q's Python 3.12.14 environment. [Raw measurements](flagship-measurements.json) and the repeatable gateway test are retained. This is one local run with potentially warm OS caches, not a comparison against the old systems, a service-level guarantee or a claim of HFT capability. Browser rendering and provider/network latency are not included.

| Operation | Median | 95th percentile | Samples |
| --- | ---: | ---: | ---: |
| Gateway status, engine idle | 7.37 ms | 14.48 ms | 30 |
| Gateway status during 20,000-event MM simulation | 7.40 ms | 16.62 ms | 35 |
| Python health through gateway during MM | 62.17 ms | 125.19 ms | 35 |
| Python health through gateway after MM | 20.25 ms | 27.84 ms | 30 |

First engine start and health response took 1.74 seconds. The seeded 20,000-event MM run plus latency sensitivity and result polling took 3.37 seconds. The retained 900-session/14-strategy synthetic diagnostic suite took 5.08 seconds including job polling and source capture. Bar and MM ZIP exports replayed with exact metrics. Owner-pipe shutdown completed in 0.52 seconds, and a subsequent restart succeeded.

Measured working sets (MiB; 1 MiB = 1,048,576 bytes):

| Point | Gateway + test harness | Python venv launcher | Actual Python runtime |
| --- | ---: | ---: | ---: |
| Engine ready | 70.9 | 4.7 | 181.2 |
| After large MM run | 115.8 | 4.7 | 221.1 |
| After full regime suite | 116.7 | 4.7 | 219.2 |

The gateway column includes the in-process test harness and downloaded artifact buffers; it is not a clean production idle-memory measurement. Python may retain allocated memory after a job. Both the launcher and actual interpreter are counted: measuring only Windows' venv launcher would materially understate memory. No Python process starts for Q's ordinary pages until an engine request is made.

The final built view chunks are approximately 13.7 KiB gzip for Allocation replay, 12.5 KiB for Portfolio research, and 14.1 KiB for Evidence, excluding shared dependencies. They are loaded on demand. The existing terminal chunk is 68.2 KiB gzip, also excluding shared dependencies. These are individual file sizes, not total download or browser memory measurements.

The architecture reduces concurrent idle processes and duplicate UI/service runtimes: one Q interface, one gateway, one lazy Python environment and one shared Python compute executor, plus a lazy Node calculation worker. Hidden research views suspend effects and polling. Large charts use bounded display samples while tables/exports preserve full observations. No numeric speedup or percentage memory reduction is claimed without a comparable before/after benchmark.

During validation, a Windows owner-pipe watcher initially blocked source-version subprocess handling. The fix uses unbuffered owner-pipe reads and gives provenance subprocesses an explicit null input. The five-second full-suite measurement above is from the successful fixed run, not the interrupted earlier attempts.
