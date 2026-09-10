#!/bin/bash
NRT_CODE_BASE="/opt/satnrt/rt-sat-to-obis"
LOG_FILE="$NRT_CODE_BASE/logs/pull_otn_sat_tags_$(date +\%Y\%m\%d_\%H\%M\%S).log"
RUN_DETAILS_CSV="$NRT_CODE_BASE/argosqc_run_details.csv"

cd "$NRT_CODE_BASE" && /opt/miniconda3/envs/rt-sat-to-obis/bin/python  "$NRT_CODE_BASE/py_nrt/run_pull_otn_sat_tags.py"   2>&1 | tee "$LOG_FILE"
EXIT_CODE=$?
