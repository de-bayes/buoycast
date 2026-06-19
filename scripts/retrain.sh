#!/bin/zsh
# Weekly retrain — runs on the Mac, ships to the VM.
#
# The e2-micro that serves the site is ~25x too slow for the streamed retrain
# (55 features + subsurface streams over ~600k rows, rebuilt by train_q +
# backtest + corr): it timed out past 4h. This Mac does the same chain in
# ~15 min, then ships the fresh model + calibration artifacts to the VM and
# triggers a publish. Serving/publishing stays always-on on the VM regardless;
# a missed week (Mac asleep) is harmless since the model is stable week-to-week.
#
# Scheduled by ~/Library/LaunchAgents/com.seiche.retrain.plist (Sun 05:30).
set -e
cd "$(dirname "$0")/.." || exit 1

PY=/opt/homebrew/bin/python3
GCLOUD=/opt/homebrew/bin/gcloud
VM=buoycast
ZONE=us-central1-a
STAGE=/tmp/seiche_ship
LOG="$HOME/Library/Logs/seiche/retrain.log"
mkdir -p "$HOME/Library/Logs/seiche"

{
  echo "=== retrain start $(date) ==="

  # 1. refresh data + retrain the full streamed pipeline locally
  $PY fetch.py
  $PY fetch_weather.py
  $PY fetch_mursst.py update || true
  $PY fetch_lmhofs.py update || true
  $PY train_q.py --refit-full
  $PY backtest.py
  $PY corr.py

  # 2. ship the artifacts the VM's publish.py reads. It only loads q_50 + the
  #    JSON, but the full quantile set ships too to keep models/ in sync.
  $GCLOUD compute ssh $VM --zone=$ZONE --quiet \
    --command="rm -rf $STAGE && mkdir -p $STAGE/models $STAGE/reports"
  $GCLOUD compute scp --zone=$ZONE --quiet \
    models/q_05.joblib models/q_25.joblib models/q_50.joblib \
    models/q_75.joblib models/q_95.joblib models/qstats.json \
    models/backtest.json "$VM:$STAGE/models/"
  $GCLOUD compute scp --zone=$ZONE --quiet \
    reports/correlations.json "$VM:$STAGE/reports/"

  # 3. install with the serving user's ownership, then republish on fresh models
  $GCLOUD compute ssh $VM --zone=$ZONE --quiet --command="\
    sudo install -o buoycast -g buoycast -m 644 $STAGE/models/* /opt/seiche/models/ && \
    sudo install -o buoycast -g buoycast -m 644 $STAGE/reports/* /opt/seiche/reports/ && \
    sudo systemctl start seiche-publish.service && \
    rm -rf $STAGE"

  echo "=== retrain ok $(date) ==="
} >> "$LOG" 2>&1
