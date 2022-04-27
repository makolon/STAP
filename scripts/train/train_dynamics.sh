#!/bin/bash

set -e

function run_cmd {
    echo ""
    echo "${CMD}"
    if [[ `hostname` == "sc.stanford.edu" ]]; then
        sbatch scripts/train/train_juno.sh "${CMD}"
    else
        ${CMD}
    fi
}

function train_dynamics {
    args=""
    args="${args} --trainer-config ${TRAINER_CONFIG}"
    args="${args} --dynamics-config ${DYNAMICS_CONFIG}"
    if [ ! -z "${POLICY_CHECKPOINTS}" ]; then
        args="${args} --policy-checkpoints ${POLICY_CHECKPOINTS}"
    fi
    args="${args} --path models/${EXP_NAME}"
    args="${args} --seed 0"
    # args="${args} --overwrite"

    CMD="python scripts/train/train_dynamics.py ${args}"
    run_cmd
}

EXP_NAME="20220426/decoupled"

TRAINER_CONFIG="configs/pybox2d/trainers/dynamics.yaml"
DYNAMICS_CONFIG="configs/pybox2d/dynamics/decoupled.yaml"
POLICY_CHECKPOINTS="models/${EXP_NAME}/placeright_img/final_model.pt models/${EXP_NAME}/pushleft_img/final_model.pt"
train_dynamics
