import torch
import pytest
import infinistore
import time
import os
import signal
import subprocess
import random
import string
import asyncio
import json
from multiprocessing import Process


RDMA_DEV = []


# Fixture to set RDMA_DEV before running tests
@pytest.fixture(scope="session", autouse=True)
def set_rdma_dev():
    global RDMA_DEV
    RDMA_DEV = get_active_rdma_devices()
    assert len(RDMA_DEV) > 0  # At least one RDMA device should be active
    print(f"Active RDMA devices: {RDMA_DEV}")


# Fixture to start the TCzpserver before running tests
@pytest.fixture(scope="module")
def server():
    server_process = subprocess.Popen(
        [
            "python",
            "-m",
            "infinistore.server",
            "--dev-name",
            f"{RDMA_DEV[0]}",
            "--link-type",
            "Ethernet",
            "--service-port",
            "92345",
            "--manage-port",
            "98080",
        ]
    )
    time.sleep(4)
    if server_process.poll() is None:
        print("Test Server process is running.")
    else:
        print("Server process failed to start or has already exited.")
        assert False
    yield
    os.kill(server_process.pid, signal.SIGINT)
    server_process.wait()


# add a flat to whether the same connection.


def generate_random_string(length):
    letters_and_digits = string.ascii_letters + string.digits  # 字母和数字的字符集
    random_string = "".join(random.choice(letters_and_digits) for i in range(length))
    return random_string


def get_active_rdma_devices():
    try:
        result = subprocess.run(
            ["rdma", "link", "-j"], capture_output=True, text=True, check=True
        )
        output = result.stdout

        active_devices = []
        devices = json.loads(output)
        for device in devices:
            if device["state"] == "ACTIVE":
                ifname = device["ifname"].split("/")[0]  # Extract mlx5_X part only
                if ifname not in active_devices:
                    active_devices.append(ifname)

        return active_devices
    except subprocess.CalledProcessError as e:
        print(f"Error while executing command: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error while parsing JSON: {e}")
        return []


def get_gpu_count():
    if torch.cuda.is_available():
        gpu_count = torch.cuda.device_count()
        return gpu_count
    else:
        return 0


@pytest.mark.parametrize("dtype", [torch.float16, torch.float32])
@pytest.mark.parametrize("new_connection", [True, False])
def test_basic_read_write_cache(server, dtype, new_connection):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
    )

    config.connection_type = infinistore.TYPE_RDMA

    conn = infinistore.InfinityConnection(config)
    conn.connect()

    # key is random string
    key = generate_random_string(10)
    src = [i for i in range(4096)]

    # local GPU write is tricky, we need to disable the pytorch allocator's caching
    src_tensor = torch.tensor(src, device="cuda:0", dtype=dtype)

    torch.cuda.synchronize(src_tensor.device)

    conn.register_mr(src_tensor)
    element_size = torch._utils._element_size(dtype)

    remote_addrs = conn.allocate_rdma([key], 4096 * element_size)
    conn.rdma_write_cache(src_tensor, [0], 4096, remote_addrs)

    conn.sync()
    conn.close()

    conn = infinistore.InfinityConnection(config)
    conn.connect()

    dst = torch.zeros(4096, device="cuda:0", dtype=dtype)

    conn.register_mr(dst)
    conn.read_cache(dst, [(key, 0)], 4096)
    conn.sync()
    assert torch.equal(src_tensor, dst)
    conn.close()


@pytest.mark.parametrize("separated_gpu", [False, True])
def test_batch_read_write_cache(server, separated_gpu):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name="RDMA_DEV[0]",
    )

    config.connection_type = infinistore.TYPE_RDMA

    # test if we have multiple GPUs
    if separated_gpu:
        if get_gpu_count() >= 2:
            src_device = "cuda:0"
            dst_device = "cuda:1"
        else:
            # skip if we don't have enough GPUs
            return
    else:
        src_device = "cuda:0"
        dst_device = "cuda:0"

    conn = infinistore.InfinityConnection(config)
    conn.connect()

    num_of_blocks = 10
    block_size = 4096
    src = [i for i in range(num_of_blocks * block_size)]

    src_tensor = torch.tensor(src, device=src_device, dtype=torch.float32)
    torch.cuda.synchronize(src_tensor.device)

    # write/read 3 times
    for i in range(3):
        keys = [generate_random_string(num_of_blocks) for i in range(10)]
        blocks = [(keys[i], i * block_size) for i in range(num_of_blocks)]
        conn.register_mr(src_tensor)
        remote_addrs = conn.allocate_rdma(keys, block_size * 4)
        conn.rdma_write_cache(
            src_tensor,
            [i * block_size for i in range(num_of_blocks)],
            block_size,
            remote_addrs,
        )

        conn.sync()

        dst = torch.zeros(
            num_of_blocks * block_size, device=dst_device, dtype=torch.float32
        )

        conn.register_mr(dst)
        conn.read_cache(dst, blocks, block_size)
        conn.sync()
        # import pdb; pdb.set_trace()
        assert torch.equal(src_tensor.cpu(), dst.cpu())
    conn.close()


@pytest.mark.parametrize("num_clients", [2])
def test_multiple_clients(num_clients):
    def run():
        config = infinistore.ClientConfig(
            host_addr="127.0.0.1",
            service_port=92345,
            link_type=infinistore.LINK_ETHERNET,
            dev_name=f"{RDMA_DEV[0]}",
        )

        config.connection_type = infinistore.TYPE_RDMA

        conn = infinistore.InfinityConnection(config)
        conn.connect()

        # key is random string
        key = generate_random_string(10)
        src = [i for i in range(4096)]

        src_tensor = torch.tensor(src, device="cuda:0", dtype=torch.float32)

        torch.cuda.synchronize(src_tensor.device)
        conn.register_mr(src_tensor)
        element_size = torch._utils._element_size(torch.float32)

        remote_addrs = conn.allocate_rdma([key], 4096 * element_size)
        conn.rdma_write_cache(src_tensor, [0], 4096, remote_addrs)

        conn.sync()
        conn.close()

        conn = infinistore.InfinityConnection(config)
        conn.connect()

        dst = torch.zeros(4096, device="cuda:0", dtype=torch.float32)
        conn.register_mr(dst)
        conn.read_cache(dst, [(key, 0)], 4096)
        conn.sync()
        assert torch.equal(src_tensor, dst)
        conn.close()

    processes = []
    for _ in range(num_clients):
        p = Process(target=run)
        p.start()
        processes.append(p)
    for i in range(num_clients):
        processes[i].join()


def test_key_check(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name="RDMA_DEV[0]",
        connection_type=infinistore.TYPE_RDMA,
    )
    conn = infinistore.InfinityConnection(config)
    conn.connect()
    key = generate_random_string(5)
    src = torch.randn(4096, device="cuda", dtype=torch.float32)
    conn.register_mr(src)
    remote_addrs = conn.allocate_rdma([key], 4096 * 4)

    torch.cuda.synchronize(src.device)

    conn.rdma_write_cache(src, [0], 4096, remote_addrs)
    conn.sync()
    assert conn.check_exist(key)
    conn.close()


def test_get_match_last_index(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name="RDMA_DEV[0]",
        connection_type=infinistore.TYPE_RDMA,
    )
    conn = infinistore.InfinityConnection(config)
    conn.connect()
    src = torch.randn(4096, device="cuda", dtype=torch.float32)
    conn.register_mr(src)
    remote_addrs = conn.allocate_rdma(["key1", "key2", "key3"], 4096 * 4)

    torch.cuda.synchronize(src.device)

    conn.rdma_write_cache(src, [0, 1024, 2048], 4096, remote_addrs)
    assert conn.get_match_last_index(["A", "B", "C", "key1", "D", "E"]) == 3
    conn.close()


def test_key_not_found(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )
    conn = infinistore.InfinityConnection(config)

    async def run():
        try:
            await conn.connect_async()
            key = "not_exist_key"
            dst = torch.randn(4096, device="cuda", dtype=torch.float32)
            conn.register_mr(dst)
            # expect raise exception
            with pytest.raises(Exception):
                await conn.read_cache_async(dst, [(key, 0)], 4096)
        finally:
            conn.close()

    asyncio.run(run())


def test_upload_cpu_download_gpu(server):
    src_config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )
    dst_config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )
    src_conn = infinistore.InfinityConnection(src_config)
    src_conn.connect()

    key = generate_random_string(5)
    src = torch.randn(4096, dtype=torch.float32, device="cpu")
    # NOTE: not orch.cuda.synchronize required for CPU tensor
    src_conn.register_mr(src)
    remote_addrs = src_conn.allocate_rdma([key], 4096 * 4)
    src_conn.rdma_write_cache(src, [0], 4096, remote_addrs)
    src_conn.sync()
    src_conn.close()

    dst_conn = infinistore.InfinityConnection(dst_config)
    dst_conn.connect()

    dst = torch.zeros(4096, dtype=torch.float32, device="cuda:0")
    dst_conn.register_mr(dst)
    dst_conn.read_cache(dst, [(key, 0)], 4096)
    dst_conn.sync()
    assert torch.equal(src, dst.cpu())
    dst_conn.close()


def test_deduplicate(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
    )

    config.connection_type = infinistore.TYPE_RDMA

    conn = infinistore.InfinityConnection(config)
    conn.connect()

    key = "duplicate_key"
    src = [i for i in range(4096)]
    src_tensor = torch.tensor(src, device="cuda:0", dtype=torch.float32)

    torch.cuda.synchronize(src_tensor.device)
    conn.register_mr(src_tensor)
    element_size = torch._utils._element_size(torch.float32)

    remote_addrs = conn.allocate_rdma([key], 4096 * element_size)
    print(remote_addrs)
    conn.rdma_write_cache(src_tensor, [0], 4096, remote_addrs)

    conn.sync()

    src2_tensor = torch.randn(4096, device="cuda:0", dtype=torch.float32)

    # test_deduplicate
    conn.register_mr(src2_tensor)
    element_size = torch._utils._element_size(torch.float32)

    remote_addrs = conn.allocate_rdma([key], 4096 * element_size)
    conn.rdma_write_cache(src_tensor, [0], 4096, remote_addrs)

    conn.sync()

    dst_tensor = torch.zeros(4096, dtype=torch.float32, device="cpu")
    conn.register_mr(dst_tensor)

    conn.read_cache(dst_tensor, [(key, 0)], 4096)
    conn.sync()

    assert torch.equal(src_tensor.cpu(), dst_tensor.cpu())
    assert not torch.equal(src2_tensor.cpu(), dst_tensor.cpu())
    conn.close()


def test_async_api(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )
    conn = infinistore.InfinityConnection(config)

    # use asyncio
    async def run():
        await conn.connect_async()
        key = generate_random_string(5)
        src = torch.randn(4096, device="cuda", dtype=torch.float32)
        dst = torch.zeros(4096, device="cuda", dtype=torch.float32)

        def register_mr():
            conn.register_mr(src)
            conn.register_mr(dst)

        await asyncio.to_thread(register_mr)
        remote_addrs = await conn.allocate_rdma_async([key], 4096 * 4)
        await conn.rdma_write_cache_async(src, [0], 4096, remote_addrs)
        await conn.read_cache_async(dst, [(key, 0)], 4096)
        assert torch.equal(src, dst)
        conn.close()

    asyncio.run(run())


def test_single_async_api(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )

    conn = infinistore.InfinityConnection(config)

    # use asyncio
    async def run():
        await conn.connect_async()
        key = generate_random_string(5)
        src = torch.randn(4096, device="cuda", dtype=torch.float32)
        dst = torch.zeros(4096, device="cuda", dtype=torch.float32)

        def register_mr():
            conn.register_mr(src)
            conn.register_mr(dst)

        await asyncio.to_thread(register_mr)

        await conn.rdma_write_cache_single_async(key, src.data_ptr(), 4096 * 4)

        await conn.read_cache_single_async(key, dst.data_ptr(), 4096 * 4)

        assert torch.equal(src, dst)
        conn.close()

    asyncio.run(run())


def test_read_non_exist_key(server):
    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )

    async def run():
        conn = infinistore.InfinityConnection(config)
        try:
            await conn.connect_async()
            dst = torch.zeros(4096, device="cuda", dtype=torch.float32)
            await asyncio.to_thread(conn.register_mr, dst)
            with pytest.raises(infinistore.InfiniStoreKeyNotFound):
                await conn.read_cache_async(dst, [("non_exist_key", 0)], 4096)
            with pytest.raises(infinistore.InfiniStoreKeyNotFound):
                await conn.read_cache_single_async(
                    "non_exist_key", dst.data_ptr(), 4096 * 4
                )
        finally:
            conn.close()

    asyncio.run(run())


@pytest.mark.benchmark
def test_benchmark(server):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [
            "python",
            f"{current_dir}/benchmark.py",
            "--service-port",
            "92345",
            "--dev-name",
            f"{RDMA_DEV[0]}",
            "--link-type",
            "Ethernet",
            "--size",
            "100",
            "--block-size",
            "32",
            "--iteration",
            "10",
            "--rdma",
        ],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    assert result.returncode == 0


@pytest.mark.parametrize("test_dtype", [torch.float32])
def test_delete_keys(server, test_dtype):
    BLOCK_SIZE = 4096
    # The count of elements in a key indexed region
    BLOB_SIZE = 1024
    KEY_COUNT = 3

    config = infinistore.ClientConfig(
        host_addr="127.0.0.1",
        service_port=92345,
        link_type=infinistore.LINK_ETHERNET,
        dev_name=f"{RDMA_DEV[0]}",
        connection_type=infinistore.TYPE_RDMA,
    )
    conn = infinistore.InfinityConnection(config)
    conn.connect()

    src_tensor = torch.randn(BLOCK_SIZE, device="cuda", dtype=test_dtype)
    # Generate the names of the keys
    keys = [generate_random_string(10) for i in range(KEY_COUNT)]

    conn.register_mr(src_tensor)
    # Allocate BLOB_SIZE elements for each key
    remote_addrs = conn.allocate_rdma(keys, BLOB_SIZE)

    conn.rdma_write_cache(
        src_tensor,
        [i * BLOB_SIZE for i in range(KEY_COUNT)],
        BLOB_SIZE,
        remote_addrs,
    )

    torch.cuda.synchronize(src_tensor.device)
    conn.sync()

    # Check all the keys exist
    for i in range(KEY_COUNT):
        assert conn.check_exist(keys[i])

    # Delete the keys at index 0 and 2
    assert conn.delete_keys([keys[0], keys[2]]) == 2

    # Verify the correctness
    assert conn.check_exist(keys[1])
    assert not conn.check_exist(keys[0])
    assert not conn.check_exist(keys[2])
