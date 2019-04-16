"""
Example command to run all 9 tasks: python launch.py --tasks COLA,SST2,MNLI,RTE,WNLI,QQP,MRPC,STSB,QNLI --checkpoint_dir ckpt --batch_size 16
"""
import faulthandler
faulthandler.enable()

import argparse
import copy
import datetime
import json
import logging
import os
from time import strftime

import numpy as np

from metal.mmtl.cxr.cxr_tasks import create_tasks_and_payloads, task_defaults, add_slice_labels
from metal.mmtl.metal_model import MetalModel, model_defaults
from metal.mmtl.trainer import MultitaskTrainer, trainer_defaults
from metal.utils import add_flags_from_config, recursive_merge_dicts

logging.basicConfig(level=logging.INFO)

def get_dir_name(models_dir):
    """Gets a directory to save the model.

    If the directory already exists, then append a new integer to the end of
    it. This method is useful so that we don't overwrite existing models
    when launching new jobs.

    Args:
        models_dir: The directory where all the models are.

    Returns:
        The name of a new directory to save the training logs and model weights.
    """
    existing_dirs = np.array(
        [
            d
            for d in os.listdir(models_dir)
            if os.path.isdir(os.path.join(models_dir, d))
        ]
    ).astype(np.int)
    if len(existing_dirs) > 0:
        return str(existing_dirs.max() + 1)
    else:
        return "1"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train MetalModel on single or multiple tasks.", add_help=False
    )

    # Model arguments
    # TODO: parse these automatically from model dict
    parser.add_argument(
        "--model_weights",
        type=str,
        default=None,
        help="Pretrained model for weight initialization",
    )

    # Slice only evaluation?
    parser.add_argument(
        "--slice_eval",
        type=int,
        default=0,
        help="True for loading model"
        )    

    # Training arguments
    parser.add_argument(
        "--override_train_config",
        type=str,
        default=None,
        help=(
            "Whether to override train_config dict with json loaded from path. "
            "This is used, e.g., for tuning."
        ),
    )

    parser = add_flags_from_config(parser, trainer_defaults)
    parser = add_flags_from_config(parser, model_defaults)
    parser = add_flags_from_config(parser, task_defaults)
    args = parser.parse_args()

    # Extract flags into their respective config files
    trainer_config = recursive_merge_dicts(
        trainer_defaults, vars(args), misses="ignore"
    )
    model_config = recursive_merge_dicts(model_defaults, vars(args), misses="ignore")
    task_config = recursive_merge_dicts(task_defaults, vars(args), misses="ignore")

    # Override config with config stored in json if specified
    if args.override_train_config is not None:
        with open(args.override_train_config, "r") as f:
            override_config = json.loads(f.read())
        config = recursive_merge_dicts(trainer_config, override_config, misses="report")

    # Set intelligent writer_config settings
    trainer_config["writer"] = "tensorboard"  # Always store tensorboard logs

    # Set splits based on split_prop
    if task_config["split_prop"]:
        # Create a valid set from train set
        task_config["split_prop"] = float(task_config["split_prop"])
        # Sampler will be used and handles shuffle automatically
        task_config["dl_kwargs"]["shuffle"] = False
        task_config["splits"] = ["train", "test"]
    else:
        task_config["splits"] = ["train", "valid", "test"]

    # Getting primary task names
    task_names = [task_name for task_name in args.tasks.split(",")]

    # Getting tasks
    tasks, payloads = create_tasks_and_payloads(task_names, **task_config)
    
    # TEST ASSERT FOR TASKS = TASKS IN PAYLOADS
    # np.array_equal(np.array([t.name for t in tasks]), np.array(payloads[0].task_names))
    model_config["verbose"] = False
    model = MetalModel(tasks, **model_config)

    if args.model_weights:
        model.load_weights(args.model_weights)

    # add metadata to trainer_config that will be logged to disk
    trainer_config["n_parameters"] = sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )

    if trainer_config["verbose"]:
        print(f"Task config:\n{task_config}")
        print(f"Model config:\n{model_config}")
        print(f"Trainer config:\n{trainer_config}")

    # Overwrite run_dir to only use one checkpoint dir
    # if args.run_dir is None:
    #    trainer_config["writer_config"]["run_dir"] = strftime("%Y_%m_%d")

    if args.run_name is None:
        trainer_config["writer_config"]["run_name"] = task_config[
            "tasks"
        ]  # + strftime("_%H_%M_%S")

    trainer = MultitaskTrainer(**trainer_config)
    # Force early instantiation of writer to write all three configs to dict
    trainer._set_writer()

    # trainer_config will get written automatically right before training
    trainer.writer.write_config(model_config, "model_config")
    trainer.writer.write_config(task_config, "task_config")

    if not args.slice_eval:
        trainer.train_model(model, payloads)
    else:
        print("Running slice evaluation only...")
        # Writing output to log where model path was
        slice_subdir = '/'.join(args.model_weights.split('/')[:-1])
        trainer.writer.log_subdir = slice_subdir 

    # evaluating slices after run complete
    slice_output = {}
    test_splits = trainer_config['metrics_config']['test_split']
    if isinstance(test_splits, str):
        test_splits = [test_splits]
    for split in test_splits:
        # Creating payloads for evaluation
        payload_names = [p.split for p in payloads]
        payload_ind = payload_names.index(split)
        slice_payload = copy.deepcopy(payloads[payload_ind])
        main_payload = copy.deepcopy(payloads[payload_ind])
        slice_output[split] = {}
        # Retargeting slices
        for tsk, slices in task_config['slice_dict'].items():
            for slc in slices:
                if not task_config['use_slices']:
                    add_slice_labels(main_payload,tsk,slc)
                main_payload.retarget_labelset(f"{tsk}:{slc}", tsk)
        # Scoring model
        main_dict = model.score(main_payload)
        main_dict = {k:v for k,v in main_dict.items() if ":" in k}
        # Printing results
        print(f"Evaluating slice performance on {split} split")
        print("Using main task heads:")
        print(main_dict)
        # Storing results
        slice_output[split]["MAIN"]=main_dict
        if task_config['use_slices']:
            slc_dict = model.score(slice_payload)
            slc_dict = {k:v for k,v in slc_dict.items() if ":" in k}
            print("Using slice task heads:")
            print(slc_dict)
            slice_output[split]["SLICE"]=slc_dict

    # Writing slice evaluation
    slice_metrics_path = os.path.join(trainer.writer.log_subdir, "slice_metrics.json")
    print(f"Writing slice metrics to {slice_metrics_path}")
    with open(slice_metrics_path, "w") as f:
        json.dump(slice_output, f, indent=1) 
