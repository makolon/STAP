#!/bin/bash
source ~/.bashrc
source ~/.zshrc
conda activate temporal_policies

# Easy
python scripts/visualize/primitives_pybox2d.py \
    --exec-config configs/pybox2d/exec/placeright2d_pushleft2d/uniform_sampling.yaml \
    --checkpoints \
    ${OUTPUTS}/temporal_policies/models/easy/placeright2d_sac/best_model.pt \
    ${OUTPUTS}/temporal_policies/models/easy/pushleft2d_sac/best_model.pt \
    --path ${OUTPUTS}/temporal_policies/visuals/easy_standard2d \
    --num-eps 50 \
    --gifs --plot-3d

# Hard
python scripts/visualize/primitives_pybox2d.py \
    --exec-config configs/pybox2d/exec/placeright2d_pushleft2d/uniform_sampling.yaml \
    --checkpoints \
    ${OUTPUTS}/temporal_policies/models/hard/placeright2d_sac_rand/best_model.pt \
    ${OUTPUTS}/temporal_policies/models/hard/pushleft2d_sac_rand/best_model.pt \
    --path ${OUTPUTS}/temporal_policies/visuals/hard_standard2d \
    --num-eps 50 \
    --gifs --plot-3d
