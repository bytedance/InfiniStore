import uvloop
import infinistore
import uuid
import torch
import asyncio
import sys


def generate_uuid():
    return str(uuid.uuid4())


config = infinistore.ClientConfig(
    host_addr="127.0.0.1",
    service_port=12345,
    log_level="info",
    connection_type=infinistore.TYPE_RDMA,
    ib_port=1,
    link_type=infinistore.LINK_ETHERNET,
    dev_name="mlx5_0",
)


async def main():
    while True:
        rdma_conn = infinistore.InfinityConnection(config)

        # FIXME: This is a blocking call, should be async
        await rdma_conn.connect_async()

        src_tensor = torch.tensor(
            [i for i in range(4096)], device="cpu", dtype=torch.float32
        )

        dst_tensor = torch.zeros(4096, device="cpu", dtype=torch.float32)

        rdma_conn.register_mr(
            src_tensor.data_ptr(), src_tensor.numel() * src_tensor.element_size()
        )
        rdma_conn.register_mr(
            dst_tensor.data_ptr(), dst_tensor.numel() * src_tensor.element_size()
        )

        keys = [generate_uuid() for _ in range(3)]

        await asyncio.gather(
            rdma_conn.rdma_write_cache_async(
                [(keys[0], 0), (keys[1], 1024 * 4)], 1024 * 4, src_tensor.data_ptr()
            ),
            rdma_conn.rdma_write_cache_async(
                [(keys[2], 2048 * 4)], 1024 * 4, src_tensor.data_ptr()
            ),
        )
        await rdma_conn.rdma_read_cache_async(
            [(keys[0], 0), (keys[1], 1024 * 4), (keys[2], 2048 * 4)],
            1024 * 4,
            dst_tensor.data_ptr(),
        )
        assert torch.equal(src_tensor[0:3072].cpu(), dst_tensor[0:3072].cpu())

        rdma_conn.close()


if sys.version_info >= (3, 11):
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
else:
    uvloop.install()
    asyncio.run(main())
