# EchoNext Mini-Model Dataset

This repository contains the dataset used to train the **EchoNext Mini-Model**, comprising a curated collection of 100,000 electrocardiograms (ECGs) sourced from Columbia and Allen hospitals.

## Dataset Overview

The dataset is divided into training, validation, and test splits. Some ECGs are labeled as `no_split` and are not included in model training.  
- The **training set** may include multiple ECGs per patient.  
- The **validation and test sets** include only the **latest ECG** per patient.  

Each ECG is accompanied by:
- Tabular features
- Waveform data
- Metadata including echocardiographic measurements and diagnostic labels

## Included Files

### 1. ECG Metadata (`EchoNext_metadata_100k.csv`)

A CSV file containing metadata and labels for each ECG record.  
**Note:** The order of ECGs in the metadata file matches the row order in the corresponding NumPy array files.
> For binary classification labels, all ECGs prior to an echo negative for SHD are labelled negative.  
> More granular labels are provided for all ECGs taken within a year prior to an echocardiogram.

#### ECG Demographic Data
- `patient_key`: De-identified patient identifier  
- `acquisition_year`: Year the ECG was acquired
- `location_setting`: Clinical context of ECG: either `inpatient`, `emergency`, `outpatient`, or `procedural`
- `race_ethnicity`: Either `hispanic`, `white`, `black`, `unknown`, `other`, `asian`
- `most_recent_ecg`: Binary flag indicating whether the ECG is the most recent for the patient

#### Raw ECG-Derived Tabular Features
- `sex`: Patient sex (0 = female, 1 = male)  
- `ventricular_rate`: Ventricular rate (beats per minute)  
- `atrial_rate`: Atrial rate (beats per minute)  
- `pr_interval`: PR interval (ms)  
- `qrs_duration`: QRS duration (ms)  
- `qt_corrected`: Corrected QT interval (ms)  
- `age_at_ecg`: Age at time of ECG acquisition (capped at 90 years)

#### Echo-Derived Features
- `aortic_stenosis_value`: Severity of aortic stenosis (none/trace, mild, moderate, severe)  
- `aortic_regurgitation_value`: Severity of aortic regurgitation  
- `mitral_regurgitation_value`: Severity of mitral regurgitation  
- `tricuspid_regurgitation_value`: Severity of tricuspid regurgitation  
- `pulmonary_regurgitation_value`: Severity of pulmonary regurgitation  
- `rv_systolic_function_value`: RV systolic function (normal to severely reduced)  
- `pericardial_effusion_value`: Pericardial effusion size (none to large)  
- `ivs_measurement`: Interventricular septum thickness (cm)  
- `lvpw_measurement`: Left ventricular posterior wall thickness (cm)  
- `pasp_value`: Pulmonary artery systolic pressure (mmHg)  
- `tr_max_velocity_value`: Max tricuspid regurgitation velocity (m/s)  
- `lvef_value`: Left ventricular ejection fraction (%)

#### Echo-Derived Binary Labels
These are binarized versions of the echo features based on clinically relevant thresholds:
- `lvef_lte_45_flag`: LVEF ≤ 45%  
- `lvwt_gte_13_flag`: LV wall thickness ≥ 1.3 cm  
- `aortic_stenosis_moderate_or_greater_flag`: Moderate or severe aortic stenosis  
- `aortic_regurgitation_moderate_or_greater_flag`: Moderate or severe aortic regurgitation  
- `mitral_regurgitation_moderate_or_greater_flag`: Moderate or severe mitral regurgitation  
- `tricuspid_regurgitation_moderate_or_greater_flag`: Moderate or severe tricuspid regurgitation  
- `pulmonary_regurgitation_moderate_or_greater_flag`: Moderate or severe pulmonary regurgitation  
- `rv_systolic_dysfunction_moderate_or_greater_flag`: Moderate or severe RV dysfunction  
- `pericardial_effusion_moderate_large_flag`: Moderate or large pericardial effusion  
- `pasp_gte_45_flag`: PASP ≥ 45 mmHg  
- `tr_max_gte_32_flag`: TR velocity ≥ 3.2 m/s  
- `shd_moderate_or_greater_flag`: Composite label indicating presence of moderate or greater structural heart disease

#### Split Information
- `split`: Indicates data partition (`train`, `val`, `test`, or `no_split`)

---

### 2. Tabular Features (`EchoNext_<SPLIT>_tabular_features.npy`)

Each file contains preprocessed tabular features for ECGs in the corresponding split.  
Shape: **N × 7**

**Note:** The order of ECGs in the NumPy array files matches the row order in the corresponding metadata file.

**Columns:**
- `sex`  
- `ventricular_rate`  
- `atrial_rate`  
- `pr_interval`  
- `qrs_duration`  
- `qt_corrected`  
- `age_at_ecg`

**Preprocessing Notes:**
- Continuous features were standardized  
- Missing values were imputed using the median (except `atrial_rate` and `pr_interval`, which were set to 0)  
- `sex` was binarized

---

### 3. Waveform Features (`EchoNext_<SPLIT>_waveforms.npy`)

Each file contains preprocessed waveform data for ECGs in the corresponding split.  
Shape: **N × 1 × 2500 × 12**  
Each ECG is a 10-second, 12-lead segment sampled at 250 Hz.

**Note:** The order of ECGs in the NumPy array files matches the row order in the corresponding metadata file.

**Waveform Preprocessing:**
- Median-filtered per lead  
- Clipped at the 0.1st and 99.9th percentiles  
- Normalized using dataset-wide mean and standard deviation


## Usage

Instructions for running inference using the EchoNext Mini-Model are available in the [GitHub repository](https://github.com/) (see Section 7).