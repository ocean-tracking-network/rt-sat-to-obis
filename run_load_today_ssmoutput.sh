#!/bin/bash
cd /opt/otn_nrt/rt-sat-to-obis &&  python py_nrt/run_load_today_nrt_results.py >> otn_nrt_pipeline_cron.log 2>&1