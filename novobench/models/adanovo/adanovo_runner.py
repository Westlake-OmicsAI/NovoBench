"""Training and testing functionality for the de novo peptide sequencing
model."""

import glob
import logging
import os
import sys
import tempfile
import uuid
import warnings
from pathlib import Path
from typing import Iterable, List, Optional, Union
from pathlib import Path
import lightning.pytorch as pln
import polars as pl
import numpy as np
import torch
import time

from lightning.pytorch.strategies import DDPStrategy
from lightning.pytorch.callbacks import ModelCheckpoint

from .adanovo_config import AdanovoConfig
from pynovo.data import ms_io
from .adanovo_dataloader import AdanovoDataset, AdanovoDataModule
from .adanovo_modeling import Spec2Pep

from pynovo.transforms import SetRangeMZ, FilterIntensity, RemovePrecursorPeak, ScaleIntensity
from pynovo.transforms.misc import Compose
from pynovo.utils.preprocessing import convert_mgf_ipc
from pynovo.data import SpectrumData
logger = logging.getLogger("adanovo")

def init_logger():
    output = "/jingbo/PyNovo/adanovo_nine.log"
    logging.captureWarnings(True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    log_formatter = logging.Formatter(
        "{asctime} {levelname} [{name}/{processName}] {module}.{funcName} : "
        "{message}",
        style="{",
    )
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(log_formatter)
    root.addHandler(console_handler)
    file_handler = logging.FileHandler(output)
    file_handler.setFormatter(log_formatter)
    root.addHandler(file_handler)
    # Disable dependency non-critical log messages.
    logging.getLogger("depthcharge").setLevel(logging.INFO)
    logging.getLogger("github").setLevel(logging.WARNING)
    logging.getLogger("h5py").setLevel(logging.WARNING)
    logging.getLogger("numba").setLevel(logging.WARNING)
    logging.getLogger("pytorch_lightning").setLevel(logging.WARNING)
    logging.getLogger("torch").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    

class AdanovoRunner:
    """A class to run Adanovo models.

    Parameters
    ----------
    config : Config object
        The adanovo configuration.
    model_filename : str, optional
        The model filename is required for eval and de novo modes,
        but not for training a model from scratch.
    """

    def __init__(
        self,
        config: AdanovoConfig,
        model_filename: Optional[str] = None,
        saved_path: str = "",
    ) -> None:
        
        
        init_logger()
        """Initialize a ModelRunner"""
        self.config = config
        self.model_filename = model_filename
        self.saved_path = saved_path

        # Initialized later:
        self.tmp_dir = None
        self.trainer = None
        self.model = None
        self.loaders = None
        self.writer = None

        # Configure checkpoints.
        if config.save_top_k is not None:
            self.callbacks = [
                ModelCheckpoint(
                    dirpath=config.model_save_folder_path,
                    monitor="valid_CELoss",
                    mode="min",
                    save_top_k=config.save_top_k,
                )
            ]
        else:
            self.callbacks = None


    @staticmethod
    def preprocessing_pipeline(min_mz=50.0, max_mz=2500.0, n_peaks: int = 150,
                               min_intensity: float = 0.01, remove_precursor_tol: float = 2.0,):
        transforms = [
            SetRangeMZ(min_mz, max_mz), 
            RemovePrecursorPeak(remove_precursor_tol),
            FilterIntensity(min_intensity, n_peaks),
            ScaleIntensity()
        ]
        return Compose(*transforms)
    

    def __enter__(self):
        """Enter the context manager"""
        self.tmp_dir = tempfile.TemporaryDirectory()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Cleanup on exit"""
        self.tmp_dir.cleanup()
        self.tmp_dir = None
        if self.writer is not None:
            self.writer.save()

    def train(
        self,
        train_df: pl.DataFrame,
        val_df: pl.DataFrame,
    ) -> None:
        """Train the Adanovo model.

        Parameters
        ----------
        train_peak_path : iterable of str
            The path to the MS data files for training.
        valid_peak_path : iterable of str
            The path to the MS data files for validation.

        Returns
        -------
        self
        """
        self.initialize_trainer(train=True)
        self.initialize_model(train=True)
        
        train_loader = AdanovoDataModule(
            df = train_df,
            n_workers=self.config.n_workers,
            batch_size=self.config.train_batch_size // self.trainer.num_devices
        ).get_dataloader(shuffle=True)
        
        val_loader = AdanovoDataModule(
            df = val_df,
            n_workers=self.config.n_workers,
            batch_size=self.config.train_batch_size // self.trainer.num_devices
        ).get_dataloader()

        start_time = time.time()
        self.trainer.fit(
            self.model,
            train_loader,
            val_loader,
        )
        training_time = time.time() - start_time
        logger.info(f"Training took {training_time:.2f} seconds")

    def evaluate(self, test_df: pl.DataFrame,) -> None:
        """Evaluate peptide sequence preditions from a trained Adanovo model.

        Parameters
        ----------
        peak_path : iterable of str
            The path with MS data files for predicting peptide sequences.

        Returns
        -------
        self
        """
        self.initialize_trainer(train=False)
        self.initialize_model(train=False)
        test_loader = AdanovoDataModule(
            df = test_df,
            n_workers=self.config.n_workers,
            batch_size=self.config.train_batch_size // self.trainer.num_devices if not self.config.calculate_precision else self.config.predict_batch_size
        ).get_dataloader()
        
        start_time = time.time()
        self.trainer.validate(self.model, test_loader)
        training_time = time.time() - start_time
        logger.info(f"Evaluating took {training_time:.2f} seconds")

    def predict(self, peak_path: Iterable[str], output: str) -> None:
        """Predict peptide sequences with a trained Adanovo model.

        Parameters
        ----------
        peak_path : str
            The path with the MS data files for predicting peptide sequences.
        output : str
            Where should the output be saved?

        Returns
        -------
        self
        """
        self.writer = ms_io.MztabWriter(Path(output).with_suffix(".mztab"))
        self.writer.set_metadata(
            self.config,
            model=str(self.model_filename),
        )

        self.initialize_trainer(train=False)
        self.initialize_model(train=False)
        self.model.out_writer = self.writer



        peak_path = Path(peak_path)
        if peak_path.is_file():
            peak_path_list = [peak_path]
        else:
            peak_path_list = list(peak_path.iterdir())
        self.writer.set_ms_run(peak_path_list)

        
        # convert to df
        test_df = convert_mgf_ipc(peak_path)

        # test_df = test_df.sample(100)
        # test loader
        test_loader = AdanovoDataModule(
            df = SpectrumData(test_df),
            n_workers=self.config.n_workers,
            batch_size=self.config.train_batch_size // self.trainer.num_devices
        ).get_dataloader()
        self.trainer.predict(self.model,test_loader)
        self.writer.save()


    def initialize_trainer(self, train: bool) -> None:
        """Initialize the lightning Trainer.

        Parameters
        ----------
        train : bool
            Determines whether to set the trainer up for model training
            or evaluation / inference.
        """
        trainer_cfg = dict(
            accelerator = self.config.accelerator,
            enable_checkpointing=False,
        )

        if train:
            if self.config.devices is None:
                devices = "auto"
            else:
                devices = self.config.devices

            additional_cfg = dict(
                devices=devices,
                callbacks=self.callbacks,
                enable_checkpointing=self.config.save_top_k is not None,
                max_epochs=self.config.max_epochs,
                num_sanity_val_steps=self.config.num_sanity_val_steps,
                strategy=self._get_strategy(),
                val_check_interval=self.config.val_check_interval,
                check_val_every_n_epoch=None,
            )
            trainer_cfg.update(additional_cfg)

        self.trainer = pln.Trainer(**trainer_cfg)

    def initialize_model(self, train: bool) -> None:
        """Initialize the Adanovo model.

        Parameters
        ----------
        train : bool
            Determines whether to set the model up for model training
            or evaluation / inference.
        """
        model_params = dict(
            dim_model=self.config.dim_model,
            n_head=self.config.n_head,
            dim_feedforward=self.config.dim_feedforward,
            n_layers=self.config.n_layers,
            dropout=self.config.dropout,
            dim_intensity=self.config.dim_intensity,
            max_length=self.config.max_length,
            residues=self.config.residues,
            max_charge=self.config.max_charge,
            precursor_mass_tol=self.config.precursor_mass_tol,
            isotope_error_range=self.config.isotope_error_range,
            min_peptide_len=self.config.min_peptide_len,
            n_beams=self.config.n_beams,
            top_match=self.config.top_match,
            n_log=self.config.n_log,
            tb_summarywriter=self.config.tb_summarywriter,
            train_label_smoothing=self.config.train_label_smoothing,
            warmup_iters=self.config.warmup_iters,
            max_iters=self.config.max_iters,
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
            out_writer=self.writer,
            calculate_precision=self.config.calculate_precision,
            s1=self.config.s1,
            s2=self.config.s2,
        )

        # Reconfigurable non-architecture related parameters for a loaded model
        loaded_model_params = dict(
            max_length=self.config.max_length,
            precursor_mass_tol=self.config.precursor_mass_tol,
            isotope_error_range=self.config.isotope_error_range,
            n_beams=self.config.n_beams,
            min_peptide_len=self.config.min_peptide_len,
            top_match=self.config.top_match,
            n_log=self.config.n_log,
            tb_summarywriter=self.config.tb_summarywriter,
            train_label_smoothing=self.config.train_label_smoothing,
            warmup_iters=self.config.warmup_iters,
            max_iters=self.config.max_iters,
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
            out_writer=self.writer,
            calculate_precision=self.config.calculate_precision,
        )

        if self.model_filename is None:
            # Train a model from scratch if no model file is provided.
            if train:
                self.model = Spec2Pep(**model_params)
                return
            # Else we're not training, so a model file must be provided.
            else:
                logger.error("A model file must be provided")
                raise ValueError("A model file must be provided")
        # Else a model file is provided (to continue training or for inference).

        if not Path(self.model_filename).exists():
            logger.error(
                "Could not find the model weights at file %s",
                self.model_filename,
            )
            raise FileNotFoundError("Could not find the model weights file")

        # First try loading model details from the weights file, otherwise use
        # the provided configuration.
        device = torch.empty(1).device  # Use the default device.
        try:
            self.model = Spec2Pep.load_from_checkpoint(
                self.model_filename, map_location=device, saved_path=self.saved_path, **loaded_model_params
            )
            print('load model.....')
            architecture_params = set(model_params.keys()) - set(
                loaded_model_params.keys()
            )
            for param in architecture_params:
                if model_params[param] != self.model.hparams[param]:
                    warnings.warn(
                        f"Mismatching {param} parameter in "
                        f"model checkpoint ({self.model.hparams[param]}) "
                        f"vs config file ({model_params[param]}); "
                        "using the checkpoint."
                    )
        except RuntimeError:
            # This only doesn't work if the weights are from an older version
            try:
                self.model = Spec2Pep.load_from_checkpoint(
                    self.model_filename,
                    map_location=device,
                    **model_params,
                )
                print('load model.....')
            except RuntimeError:
                raise RuntimeError(
                    "Weights file incompatible with the current version of "
                    "Adanovo. "
                )


    def _get_strategy(self) -> Union[str, DDPStrategy]:
        """Get the strategy for the Trainer.

        The DDP strategy works best when multiple GPUs are used. It can work
        for CPU-only, but definitely fails using MPS (the Apple Silicon chip)
        due to Gloo.

        Returns
        -------
        Union[str, DDPStrategy]
            The strategy parameter for the Trainer.

        """
        if self.config.accelerator in ("cpu", "mps"):
            return "auto"
        elif self.config.devices == 1:
            return "auto"
        elif torch.cuda.device_count() > 1:
            return DDPStrategy(find_unused_parameters=False, static_graph=True)
        else:
            return "auto"

