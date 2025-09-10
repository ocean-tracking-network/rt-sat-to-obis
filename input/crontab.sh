#!/bin/bash
cd ~/projects/rt-sat-to-obis/input/
for f in *; do
  if [ -d "$f" ]; then
    cd $f
    # Find the config file in this folder
    # or quit
    for config in $(ls ./config_*.json);
    do
    # run the script using the config file
      echo $config
      Rscript '../run_ArgosQC.R' $config  > "${config}.log" 2>&1
    done
    cd ..
  fi
done