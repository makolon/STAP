#!/bin/bash

# Install scod-regression
cd /home/$USER/STAP/third_party/scod-regression
pip install -e .
cd -

# Run CMD from Docker
"$@"