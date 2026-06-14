#!/bin/zsh
# hourly: pull latest buoy obs + weather forecast, regenerate site/data.json
cd "$(dirname "$0")/.." || exit 1
/opt/homebrew/bin/python3 publish.py >> ~/Library/Logs/seiche/refresh.log 2>&1
echo "refresh ok $(date)" >> ~/Library/Logs/seiche/refresh.log
