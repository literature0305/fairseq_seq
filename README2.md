1. Google drive에서 pretrained LM 다운로드
  **링크: https://drive.google.com/file/d/1FaZnwLX2rWSMq1D5LfdVmdXvVQNMXylJ/view?usp=sharing
  **LM configure
      - 모델: FairSeq-RoBERTa
      - Tokenization: letter (wav2vec2.0 fine tuning 기본 설정과 동일한 vocabulary를 공유함)
      - 학습 데이터셋: Libri Corpus
2. 압축 풀기 tar -xvf pretrained_libri-letter-bert.tar.gz
3. git clone https://github.com/literature0305/fairseq_seq.git
4. fairseq_seq/examples/wav2vec/config/finetuning/base_100h_sdt_kd.yaml에서 다운 받은 LM 경로 설정 해주기
5. ./0_prepare_w2v_libri100.sh (Libri DB 경로 설정 해주기 datadir=)
6. ./2_fintuning_with-libri100_sdt-kd.sh (경로 설정 해주기)
7. ./3_decode_viterbi.sh (경로 설정 해주기)
