# NovoBench: Benchmark $de$ $novo$ peptide sequencing algorithms
<p>
  <a href="https://github.com/pytorch/pytorch"> <img src="https://img.shields.io/badge/PyTorch-%23EE4C2C.svg?style=for-the-badge&logo=PyTorch&logoColor=white" height="22px"></a>
  <a href="https://github.com/Lightning-AI/pytorch-lightning"> <img src="https://img.shields.io/badge/-Lightning-792ee5?logo=pytorchlightning&logoColor=white" height="22px"></a>
<p>

<p align="center" width="100%">
  <img src='./images/all.png' width="600%">
</p>

## Introduction
Tandem mass spectrometry has played a pivotal role in advancing proteomics, enabling the analysis of protein composition in biological tissues. Many deep learning methods have been developed for $de$ $novo$ peptide sequencing task, i.e., predicting the peptide sequence for the observed mass spectrum. However, two key challenges seriously hinder the further research of this important task. Firstly, since there is no consensus for the evaluation datasets, the empirical results in different research papers are often not comparable, leading to unfair comparison. Secondly, the current methods are usually limited to amino acid-level or peptide-level precision and recall metrics. In this work, we present the first unified benchmark NovoBench for $de$ $novo$ peptide sequencing, which comprises diverse mass spectrum data, integrated models, and comprehensive evaluation metrics. Recent impressive methods, including DeepNovo, PointNovo, Casanovo, InstaNovo, AdaNovo and $\pi$-HelixNovo are integrated into our framework. In addition to amino acid-level and peptide-level precision and recall, we also evaluate the models' performance in terms of identifying post-tranlational modifications (PTMs), efficiency and robustness to peptide length, noise peaks and missing fragment ratio, which are important influencing factors while seldom be considered. Leveraging this benchmark, we conduct a large-scale study of current methods, report many insightful findings that open up new possibilities for future development. 


## Installation
This project has provided an environment setting file of conda, users can easily reproduce the environment by the following commands:
```shell
conda env create -f novobench.yaml
conda activate novobench
```

## Train a new  model 
To train a model from scratch, run:
```shell
python tests/casanovo.py --mode train --data_path parquet_path --model_path ckpt_path  --config_path config_path
```


## Sequence mass spectra
To sequence the mass spectra with NovoBench, use the following command:
```shell
python tests/casanovo.py --mode seq --data_path parquet_path --model_path ckpt_path --denovo_output_path csv_path --config_path config_path
``` 