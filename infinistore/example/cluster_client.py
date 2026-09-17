from infinistore import (
    ClientConfig,
    Logger,
    InfinityConnection,
    ConsulClusterMgr,
    NoClusterMgr,
)
import uvloop
import torch
import time
import asyncio
import threading

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop = asyncio.new_event_loop()
t = threading.Thread(target=start_loop, args=(loop,))
t.start()

def run(conn, src_device="cuda:0", dst_device="cuda:2"):
    src_tensor = torch.tensor(
        [i for i in range(4096)], device=src_device, dtype=torch.float32
    )
    conn.register_mr(
        src_tensor.data_ptr(), src_tensor.numel() * src_tensor.element_size()
    )
    keys_offsets = [("key1", 0), ("key2", 1024 * 4), ("key3", 2048 * 4)]
    now = time.time()

    future = asyncio.run_coroutine_threadsafe(
       conn.rdma_write_cache_async(keys_offsets, 1024 * 4, src_tensor.data_ptr()), loop
    )

    future.result()
    print(f"write elapse time is {time.time() - now}")

    dst_tensor = torch.zeros(4096, device=dst_device, dtype=torch.float32)
    conn.register_mr(
        dst_tensor.data_ptr(), dst_tensor.numel() * dst_tensor.element_size()
    )
    now = time.time()

    future = asyncio.run_coroutine_threadsafe(
        conn.rdma_read_cache_async(keys_offsets, 1024 * 4, dst_tensor.data_ptr()), loop
    )
    future.result()
    print(f"read elapse time is {time.time() - now}")

    assert torch.equal(src_tensor[0:1024].cpu(), dst_tensor[0:1024].cpu())
    assert torch.equal(src_tensor[1024:2048].cpu(), dst_tensor[1024:2048].cpu())

if __name__ == "__main__":
    cluster_mode = True
    if cluster_mode:
        cluster_mgr = ConsulClusterMgr(bootstrap_address="127.0.0.1:8500")
    else:
        cluster_mgr = NoClusterMgr(bootstrap_address="127.0.0.1:8081", service_manage_port=8081)        
    # Refresh cluster first to get the alive service nodes
    cluster_mgr.refresh_service_nodes()
    #asyncio.create_task(cluster_mgr.refresh_task())
    cluster_mgr.refresh_task()
    
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
        loop.call_soon_threadsafe(loop.stop)
        t.join()
