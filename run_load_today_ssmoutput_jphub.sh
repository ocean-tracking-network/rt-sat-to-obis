#!/bin/bash
NRT_CODE_BASE="/opt/satnrt/rt-sat-to-obis"
LOG_FILE="$NRT_CODE_BASE/logs/run_load_today_ssmoutput_$(date +\%Y\%m\%d_\%H\%M\%S).log"
RUN_DETAILS_CSV="$NRT_CODE_BASE/argosqc_run_details.csv"
EMAILTO="yinghuan.niu@oceantrack.org"

cd "$NRT_CODE_BASE" && /opt/miniconda3/envs/rt-sat-to-obis/bin/python  "$NRT_CODE_BASE/python py_nrt/run_load_all_sat_qc_results.py" > $LOG_FILE  2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    # Send email with the error output
    if [ -s "$LOG_FILE" ]; then
          EMAIL_BODY="/tmp/email_body_$(date +\%Y\%m\%d_\%H\%M\%S).txt"
          echo "=== SCRIPT OUTPUT ===" > "$EMAIL_BODY"
          cat "$LOG_FILE" >> "$EMAIL_BODY"
          echo "" >> "$EMAIL_BODY"
    fi

    # Check if argosqc_run_details.csv exists
    if [ -f "$RUN_DETAILS_CSV" ]; then
        echo "=== LAST 20 ROWS OF argosqc_run_details.csv ===" >> "$EMAIL_BODY"
        echo "File: $RUN_DETAILS_CSV" >> "$EMAIL_BODY"
        echo "Last modified: $(stat -c %y "$RUN_DETAILS_CSV" 2>/dev/null || date -r "$RUN_DETAILS_CSV")" >> "$EMAIL_BODY"
        echo "" >> "$EMAIL_BODY"
        tail -20 "$RUN_DETAILS_CSV" >> "$EMAIL_BODY"
        echo "" >> "$EMAIL_BODY"
        echo "Total lines in file: $(wc -l < "$RUN_DETAILS_CSV")" >> "$EMAIL_BODY"
    fi

    # Check if load_today_ssmoutput_summary.csv exists
    if [ -f "$RUN_DETAILS_CSV" ]; then
        echo "" >> "$EMAIL_BODY"
        echo "=== The latest load_today_ssmoutput_summary.csv ===" >> "$EMAIL_BODY"
        echo "File: $RUN_DETAILS_CSV" >> "$EMAIL_BODY"
        echo "Last modified: $(stat -c %y "$RUN_DETAILS_CSV" 2>/dev/null || date -r "$RUN_DETAILS_CSV")" >> "$EMAIL_BODY"
        cat "$RUN_DETAILS_CSV" >> "$EMAIL_BODY"
    fi
    mail -s "FAILED (Exit Code: $EXIT_CODE) - Cron Job: run_load_today_ssmoutput.sh" "$EMAILTO" < "$EMAIL_BODY"

fi

# Clean up log files
if [ -f "$LOG_FILE" ] && [ ! -s "$LOG_FILE" ]; then
    rm -f "$LOG_FILE"
fi
