#!/bin/bash
cd /opt/otn_nrt/rt-sat-to-obis &&  python py_nrt/run_argosqc_parallel.py >> otn_nrt_pipeline_cron.log 2>&1