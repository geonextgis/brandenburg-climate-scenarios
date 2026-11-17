#!/usr/bin/env bash
# Rebuild the RIA 3 GA figures from data/processed/consolidated.
set -euo pipefail
cd "$(dirname "$0")"
python 01_extract.py --jobs 28
python 02_aggregate.py
for f in fig1_model_evaluation fig2_yield_trajectories fig3_yield_change_maps \
         fig4_water_phenology fig5_nitrogen_tradeoff fig6_sustainability_scorecard; do
    python "$f.py"
done
