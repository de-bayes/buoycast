#!/bin/zsh
# weekly: refresh all history, retrain production models on everything, republish
cd "$(dirname "$0")/.." || exit 1
{
  /opt/homebrew/bin/python3 fetch.py &&
  /opt/homebrew/bin/python3 fetch_weather.py &&
  /opt/homebrew/bin/python3 train_q.py --refit-full &&
  /opt/homebrew/bin/python3 publish.py &&
  echo "retrain ok $(date)"
} >> ~/Library/Logs/seiche/retrain.log 2>&1
