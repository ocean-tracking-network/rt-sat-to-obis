#!/bin/bash
cd /opt/otn_nrt/rt-sat-to-obis &&  python py_nrt/run_argosqc_parallel.py >> /var/log/argosqc_cron.log 2>&1