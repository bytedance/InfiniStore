from infinistore import (
    ClientConfig,
    InfinityConnection,
)
import infinistore
import torch
import time


def generate_random_string(length):
    import string
    import random

    letters_and_digits = string.ascii_letters + string.digits
    random_string = "".join(random.choice(letters_and_digits) for i in range(length))
    return random_string


def run(conn, src_device="cuda:0", dst_device="cuda:2"):
    src_tensor = torch.tensor(
        [i for i in range(4096)], device=src_device, dtype=torch.float32
    )
    conn.register_mr(src_tensor)

    keys = ["key1", "key2", "key3"]
    remote_addr = conn.allocate_rdma(
        keys, 1024 * 4
    )  # 1024(block_size) * 4(element size)
    # print(f"remote_addr: {remote_addr}")
    now = time.time()

    conn.rdma_write_cache(src_tensor, [0, 1024, 2048], 1024, remote_addr)

    print(f"write elapse time is {time.time() - now}")

    before_sync = time.time()
    conn.sync()
    print(f"sync elapse time is {time.time() - before_sync}")

    dst_tensor = torch.zeros(4096, device=dst_device, dtype=torch.float32)

    conn.register_mr(dst_tensor)
    now = time.time()

    conn.read_cache(dst_tensor, [("key1", 0), ("key2", 1024)], 1024)

    conn.sync()
    print(f"read elapse time is {time.time() - now}")

    assert torch.equal(src_tensor[0:1024].cpu(), dst_tensor[0:1024].cpu())
    assert torch.equal(src_tensor[1024:2048].cpu(), dst_tensor[1024:2048].cpu())


if __name__ == "__main__":
    config = ClientConfig(
        host_addr="127.0.0.1",
        service_port=12345,
        log_level="info",
        connection_type=infinistore.TYPE_RDMA,
        ib_port=1,
        link_type=infinistore.LINK_ETHERNET,
        dev_name="mlx5_0",
    )
    rdma_conn = InfinityConnection(config)
    try:
        rdma_conn.connect()
        m = [
            ("cpu", "cuda:0"),
            ("cuda:0", "cuda:1"),
            ("cuda:0", "cpu"),
            ("cpu", "cpu"),
        ]
        for src, dst in m:
            print(f"rdma connection: {src} -> {dst}")
            run(rdma_conn, src, dst)
    finally:
        rdma_conn.close()
