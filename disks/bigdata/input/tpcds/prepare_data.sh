#!/bin/bash

set -eux

SCALE=1

TPCDS_KIT_DIR=~/tpcds-kit
TMP_DIR=/tmp/tpcds_sf$SCALE
HDFS_DIR=/bench/tpcds/raw/sf$SCALE

rm -rf $TPCDS_KIT_DIR
git clone https://github.com/databricks/tpcds-kit.git $TPCDS_KIT_DIR

pushd ${TPCDS_KIT_DIR}/tools

sudo apt-get update && sudo apt-get install -y \
    gcc make flex bison byacc

make OS=LINUX -j`nproc`

rm -rf $TMP_DIR && mkdir -p $TMP_DIR
./dsdgen -SCALE $SCALE -DIR $TMP_DIR -FORCE

hdfs dfs -rm -r $HDFS_DIR || true
hdfs dfs -mkdir -p $HDFS_DIR
hdfs dfs -put -f $TMP_DIR/*.dat $HDFS_DIR
