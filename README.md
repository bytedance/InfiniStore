[![Run pre-commit checks](https://github.com/bytedance/InfiniStore/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/bd-iaas-us/InfiniStore/actions/workflows/pre-commit.yml)
[![Slack](https://img.shields.io/badge/Slack-Join%20Us-blue?logo=slack)](https://vllm-dev.slack.com/archives/C07VCUQLE1F)
[![Docs](https://img.shields.io/badge/docs-available-brightgreen)](https://bytedance.github.io/InfiniStore/)

# What's InfiniStore

InfiniStore is an open-source high-performance KV store. It's designed to support LLM Inference clusters, whether the cluster is in prefill-decoding disaggregation mode or not. InfiniStore provides high-performance and low-latency KV cache transfer and KV cache reuse among inference nodes in the cluster.

In addition to inference clusters, InfiniStore can also be used as a standalone KV store to integrate with any other LLM training or inference services.

# Usage

There are two major scenarios how InfiniStore supports :

* Prefill-Decoding disaggregation clusters: in such mode inference workloads are separated into two node pools: prefill nodes and decoding nodes. InfiniStore enables KV cache transfer among these two types of nodes, and also KV cache reuse.
* Non-disaggregated clusters: in such mode prefill and decoding workloads are mixed on every node. Infinistore serves as an extra large KV cache pool in addition to GPU cache and local CPU cache, and also enables cross-node KV cache reuse.



![InfiniStore Usage](/./docs/source/img/InfiniStore-usage.png)

Currently InfiniStore has been integrated with vLLM. The integration is done via [LMCache](https://github.com/LMCache/LMCache) for the flexibility purpose.

Integration with SGLang and other inference engines are in progress.

# Installation

## Install from PIP

Most users just need to deploy and run InfiniStore, and they don't need to understand how InfiniStore works internally. For these users, PIP is the recommended way to install:

```
pip install infinistore
```

## Development Installation

For users who need to understand how InfiniStore code works or make code contributions to InfiniStore, it's recommended to install from source code:

```client example
apt install libuv1-dev
apt install libflatbuffers-dev
apt install libspdlog-dev libfmt-dev
apt install ibverbs-utils libibverbs-dev
apt install libboost-dev libboost-stacktrace-dev
pip install --no-build-isolation -e .
pip install pre-commit
pre-commit install
```

## Verify Your Installation

After installation, either from PIP or from source code, run the following command to verify your installation is successful:

```
infinistore --manage-port 8088
curl http://127.0.0.1:8088/selftest
```

# Run InfiniStore

## Run As a Standalone Service

1. **Start InfiniStore Server**

The first step is to start an InfiniStore server. The server can be running on a GPU machine or a CPU machine.

Your server machine may be equipped with TCP network or RDMA network. The command line to start a server varies depending on the network configurations:

For TCP/IP Network:

```
infinistore --service-port 12345
```

For RDMA(RoCE):

```
infinistore --service-port 12345 --dev-name mlx5_0 --link-type Ethernet
```

For RDMA(Infiniband):

```
infinistore --service-port 12345 --dev-name mlx5_0 --link-type IB
```

2. **Run InfiniStore Client**

Check the following example code to run an InfiniStore client:

* ```infinistore/example/client.py```
* ```infinistore/example/client_async.py```
* ```infinistore/example/client_async_single.py```

## Run infinistore server in cluster mode

1. **Start consul cluster**
Infinistore leverages consul to manage the membership of service nodes, so you must setup a consul cluster in order to run infinistore in cluster mode.

  a. Run a consul cluster with a single node

```shell
    docker run -d \
       --name=consul \
       --network=host \
       -e CONSUL_BIND_INTERFACE=eth0 \
       -e CONSUL_CLIENT_ADDR=0.0.0.0 \
       -p 8500:8500 \
       hashicorp/consul   

  b. Start a consul cluster with three nodes
# On the first node
```shell
    docker run -d \
       --name consul-node1 \
       -p 8301:8301 -p 8301:8301/udp \
       -p 8302:8302 -p 8302:8302/udp \
       -p 8500:8500 -p 8300:8300 \
       -advertise {ip of first node} \
       -server \
       -bootstrap-expect=3 \
       hashicorp/consul    

# On the second node
```shell
    docker run -d \
       --name consul-node2 \
       -p 8301:8301 -p 8301:8301/udp \
       -p 8302:8302 -p 8302:8302/udp \
       -p 8500:8500 -p 8300:8300 \
       -advertise {ip of the second node} \
       -server \
       hashicorp/consul \
       -join consul-node1

# On the third node
```shell
    docker run -d \
       --name consul-node3 \
       -p 8301:8301 -p 8301:8301/udp \
       -p 8302:8302 -p 8302:8302/udp \
       -p 8500:8500 -p 8300:8300 \
       -advertise {ip of the third node} \
       -server \
       hashicorp/consul \
       -join consul-node1

2. **Start InfiniStore Server**
For RDMA, the followings are the command to start the infinistore store on two nodes(you can add more nodes)

# On the first node(may be different from consul cluster node)
```shell
    infinistore --service-port 12345 \
       --dev-name mlx5_0 --link-type Ethernet \
       --manage-port 8081 --bootstrap-ip {ip of one of the consul cluster nodes}:8500 \
       --service-id infinistore1 --cluster-mode \
       --host {ip of the current host}

# On the second node(may be different from consul cluster node)
```shell
    infinistore --service-port 12345 \
       --dev-name mlx5_0 --link-type Ethernet \
       --manage-port 8081 --bootstrap-ip {ip of one of the consul cluster nodes}:8500 \
       --service-id infinistore1 --cluster-mode \
       --host {ip of the current host}

## Run Within a vLLM Cluster

As illustrated in the previous section, InfiniStore enables different functionalities in a vLLM cluster: KV cache transfer between prefill nodes and decoding nodes, extended KV cache pool, cross-node KV cache reuse, etc.

The setup will varies depending on the specific vLLM cluster configurations. But usually it requires the following installations:

* Install vLLM on all nodes
* Install LMCache on all nodes
* Install InfiniStore on all nodes

# Contribute to InfiniStore

InfiniStore is an open-source project and community. We welcome anyone who is interested in helping improve InfiniStore, whether code contributions, document contributions or any other contributions.

If you are submitting a code change, run the following unit test and pre-commit check to ensure your code change doesn't break existing features before submitting the PR:

1. **Make your code changes**

   Just clone this repo, make code changes according to your feature design.

2. **Run Unit Tests**

```
pytest infinistore/test_infinistore.py
```

3. **Run Pre-commit Checks**

```
pre-commit run --all-files
```

4. **Submit PR**

If you code change passes both unit tests and pre-commit checks, submit the PR.
