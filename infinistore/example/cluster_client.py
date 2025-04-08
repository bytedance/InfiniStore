from infinistore import (
    ClientConfig,
    check_supported,
    Logger,
    InfinityConnection,
    ConsulClusterMgr,
    NoClusterMgr,
)
import uvloop
import torch
import time
import asyncio
import sys

def run(conn, src_device="cuda:0", dst_device="cuda:2"):
    check_supported()
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

async def main():
    cluster_mode = True
    if cluster_mode:
        cluster_mgr = ConsulClusterMgr(bootstrap_address="127.0.0.1:8500")
    else:
        cluster_mgr = NoClusterMgr(bootstrap_address="127.0.0.1:8081", service_manage_port=8081)        
    # Refresh cluster first to get the alive service nodes
    cluster_mgr.refresh_service_nodes()
    asyncio.create_task(cluster_mgr.refresh_task())
    
    rdma_conn = cluster_mgr.get_connection()

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

if sys.version_info >= (3, 11):
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
else:
    uvloop.install()
    asyncio.run(main())

