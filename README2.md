**Paper Title**: Cross_modal_learning_for_CTC_based_ASR__Leveraging_CTC_BERTScore_and_sequence_level_training (ASRU2023)

1. Download pretrained Language Model (LM) from Google Drive
   **Link**: [https://drive.google.com/file/d/1FaZnwLX2rWSMq1D5LfdVmdXvVQNMXylJ/view?usp=sharing](https://drive.google.com/file/d/1FaZnwLX2rWSMq1D5LfdVmdXvVQNMXylJ/view?usp=sharing)
   **LM Configuration**
       - Model: FairSeq-RoBERTa
       - Tokenization: letter (shares the same vocabulary as the default setting for wav2vec2.0 fine-tuning)
       - Training Dataset: Libri Corpus
2. Unzip with `tar -xvf pretrained_libri-letter-bert.tar.gz`
3. Clone the repository: `git clone https://github.com/literature0305/fairseq_seq.git`
4. Set the downloaded LM path in `fairseq_seq/examples/wav2vec/config/finetuning/base_100h_sdt_kd.yaml`
5. Run `./0_prepare_w2v_libri100.sh` (Set the Libri DB path: `datadir=`)
6. Run `./2_fintuning_with-libri100_sdt-kd.sh` (Set the path)
7. Run `./3_decode_viterbi.sh` (Set the path)
8. Baseline Experiment: `./2_fintuning_with-libri100.sh`
9. Experimental Results (using a single 3090 GPU)

   | name     | SDT loss                         | test_clean | dev_clean | test_other | dev_other |
   |----------|----------------------------------|------------|-----------|------------|-----------|
   | Baseline | x                                | 6.13       | 6.06      | 12.95      | 13.43     |
   | SDT-1    | Projection: speech axis          | 5.56       | 5.54      | 12.87      | 13.39     |
   | SDT-2    | MAS (monotonic alignment search) | 5.48       | 5.57      | 12.62      | 13.29     |

---
