#!/bin/bash
source .venv/bin/activate
echo "Starting SUBMISSION mode..."
python client.py --key ak_xfRmCG3AwHhwY3IcTUH9OgB5Dsw99raP --mode submission --seconds 4000 > submission.log 2>&1
echo "Starting FINAL mode..."
python client.py --key ak_xfRmCG3AwHhwY3IcTUH9OgB5Dsw99raP --mode final --seconds 5000 > final.log 2>&1
echo "All done."
