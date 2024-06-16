"""Mass spectrometry file type input/output operations."""

import collections
import csv
import operator
import os
import re
from pathlib import Path
from typing import List

import natsort



class MztabWriter:
    """
    Export spectrum identifications to an mzTab file.

    Parameters
    ----------
    filename : str
        The name of the mzTab file.
    """

    def __init__(self, filename: str):
        self.filename = filename
        self.metadata = [
            # ("mzTab-version", "1.0.0"),
            # ("mzTab-mode", "Summary"),
            # ("mzTab-type", "Identification"),
            # (
            #     "description",
            #     f"Casanovo identification file "
            #     f"{os.path.splitext(os.path.basename(self.filename))[0]}",
            # ),
            # ("software[1]", f"[MS, MS:1003281, Casanovo, ]"),
            # (
            #     "psm_search_engine_score[1]",
            #     "[MS, MS:1001143, search engine specific score for PSMs, ]",
            # ),
        ]
        self._run_map = {}
        self.psms = []

    def set_metadata(self, config, **kwargs) -> None:

        """
        Specify metadata information to write to the mzTab header.

        Parameters
        ----------
        config : Config
            The active configuration options.
        kwargs
            Additional configuration options (i.e. from command-line arguments).
        """
        # Derive the fixed and variable modifications from the residue alphabet.
        known_mods = {
            "+57.021": "[UNIMOD, UNIMOD:4, Carbamidomethyl, ]",
            "+15.995": "[UNIMOD, UNIMOD:35, Oxidation, ]",
            "+0.984": "[UNIMOD, UNIMOD:7, Deamidated, ]",
            "+42.011": "[UNIMOD, UNIMOD:1, Acetyl, ]",
            "+43.006": "[UNIMOD, UNIMOD:5, Carbamyl, ]",
            "-17.027": "[UNIMOD, UNIMOD:385, Ammonia-loss, ]",
        }
        residues = collections.defaultdict(set)
        # casanovo
        dict_config = vars(config)
        for aa, mass in dict_config['residues'].items() :
            aa_mod = re.match(r"([A-Z]?)([+-]?(?:[0-9]*[.])?[0-9]+)", aa)
            if aa_mod is None:
                residues[aa].add(None)
            else:
                residues[aa_mod[1]].add(aa_mod[2])
        fixed_mods, variable_mods = [], []
        for aa, mods in residues.items():
            if len(mods) > 1:
                for mod in mods:
                    if mod is not None:
                        variable_mods.append((aa, mod))
            elif None not in mods:
                fixed_mods.append((aa, mods.pop()))

        # Add all config values to the mzTab metadata section.
        if len(fixed_mods) == 0:
            self.metadata.append(
                (
                    "fixed_mod[1]",
                    "[MS, MS:1002453, No fixed modifications searched, ]",
                )
            )
        else:
            for i, (aa, mod) in enumerate(fixed_mods, 1):
                self.metadata.append(
                    (
                        f"fixed_mod[{i}]",
                        known_mods.get(mod, f"[CHEMMOD, CHEMMOD:{mod}, , ]"),
                    )
                )
                self.metadata.append(
                    (f"fixed_mod[{i}]-site", aa if aa else "N-term")
                )
        if len(variable_mods) == 0:
            self.metadata.append(
                (
                    "variable_mod[1]",
                    "[MS, MS:1002454, No variable modifications searched,]",
                )
            )
        else:
            for i, (aa, mod) in enumerate(variable_mods, 1):
                self.metadata.append(
                    (
                        f"variable_mod[{i}]",
                        known_mods.get(mod, f"[CHEMMOD, CHEMMOD:{mod}, , ]"),
                    )
                )
                self.metadata.append(
                    (f"variable_mod[{i}]-site", aa if aa else "N-term")
                )
        for i, (key, value) in enumerate(kwargs.items(), 1):
            self.metadata.append(
                (f"software[1]-setting[{i}]", f"{key} = {value}")
            )
        for i, (key, value) in enumerate(dict_config.items(), len(kwargs) + 1):
            if key not in ("residues",):
                self.metadata.append(
                    (f"software[1]-setting[{i}]", f"{key} = {value}")
                )

    def set_ms_run(self, peak_filenames: List[str]) -> None:
        """
        Add input peak files to the mzTab metadata section.

        Parameters
        ----------
        peak_filenames : List[str]
            The input peak file name(s).
        """
        for i, filename in enumerate(natsort.natsorted(peak_filenames), 1):
            filename = os.path.abspath(filename)
            self.metadata.append(
                (f"ms_run[{i}]-location", Path(filename).as_uri()),
            )
            self._run_map[filename] = i

    def save(self) -> None:
        """
        Export the spectrum identifications to the mzTab file.
        """
        with open(self.filename, "w") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator=os.linesep)
            # Write metadata.
            for row in self.metadata:
                writer.writerow(["MTD", *row])
            # Write PSMs.
            writer.writerow(
                [
                    "PSH",
                    "sequence",
                    "PSM_ID",
                    "search_engine_score",
                    "charge",
                    "exp_mass_to_charge",
                    "calc_mass_to_charge",
                    "opt_ms_run[1]_aa_scores",
                ]
            )
            for i, psm in enumerate(
                natsort.natsorted(self.psms, key=operator.itemgetter(1)), 1
            ):
                writer.writerow(
                    [
                        "PSM",
                        psm[0],  # sequence
                        i,  # PSM_ID
                        psm[2],  # search_engine_score[1]
                        psm[3],  # charge
                        psm[4],  # exp_mass_to_charge
                        psm[5],  # calc_mass_to_charge
                        psm[6],  # opt_ms_run[1]_aa_scores
                    ]
                )