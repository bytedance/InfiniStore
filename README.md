[![Run pre-commit checks](https://github.com/bd-iaas-us/infiniStore/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/bd-iaas-us/infiniStore/actions/workflows/pre-commit.yml)
[![Slack](https://img.shields.io/badge/Slack-Join%20Us-blue?logo=slack)](https://vllm-dev.slack.com/archives/C07VCUQLE1F)
[![Docs](https://img.shields.io/badge/docs-available-brightgreen)](https://bd-iaas-us.github.io/InfiniStore/)


## pre-required

* kernel module nv_peer_mem https://github.com/Mellanox/nv_peer_memory for RDMAGPUDirect

## install

```
pip install infinistore
```

## run

For RDMA RoCE

```
infinistore --service-port 12345 --dev-name mlx5_0 --link-type Ethernet
```

For RDMA Infiniband

```
infinistore --service-port 12345 --dev-name mlx5_0 --link-type IB
```

## build on ubuntu

```
apt install libuv1-dev
apt install libflatbuffers-dev
apt install libspdlog-dev libfmt-dev
apt install ibverbs-utils libibverbs-dev
apt install libboost-dev libboost-stacktrace-dev
pip install -e .
pip install pre-commit
pre-commit install
```
## client example

check example code

* ```infinistore/example/client.py```
* ```infinistore/example/client_async.py```
* ```infinistore/example/client_async_single.py```


## unit test

```
pytest infinistore/test_infinistore.py
```

## pre-commit

```
pre-commit run --all-files
```
