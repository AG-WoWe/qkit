#!/bin/bash
set -x

# Remove extra quotes from file path
FILE="${1//\'/}"   # deletes single quotes
FILE="${FILE//\"/}" # deletes double quotes

# Place folder location of virtual qkit environemnt here
cd ~/virtual_environments/with-system/ #path_venv
source bin/activate

echo "File passed to Python: $FILE"
ls -l "$FILE"

# Place folder location of main.py in qkit repo here (qkit/src/qkit/gui/qviewkit) 
python ~/qkit/src/qkit/gui/qviewkit/main.py -f "$FILE"

