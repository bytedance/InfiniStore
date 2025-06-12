import infinistore
import uuid
import asyncio
import ctypes
from infinistore import Desc


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


def get_ptr(mv: memoryview):
    return ctypes.addressof(ctypes.c_char.from_buffer(mv))


async def main():
    rdma_conn = infinistore.InfinityConnection(config)

    # FIXME: This is a blocking call, should be async
    await rdma_conn.connect_async()

    key = generate_uuid()

    size = 128 * 1024
    src = bytearray(size)
    dst = memoryview(bytearray(size))

    def register_mr():
        rdma_conn.register_mr(get_ptr(src), len(src))
        rdma_conn.register_mr(get_ptr(dst), len(dst))

    await asyncio.to_thread(register_mr)

    # set src
    for i in range(size):
        src[i] = i % 256

    is_exist = await asyncio.to_thread(rdma_conn.check_exist, key)
    assert not is_exist

    await rdma_conn.rdma_write_cache_async2(
        [Desc(key, get_ptr(src), size), Desc(key + "_1", get_ptr(src), size)]
    )
    ret = await rdma_conn.rdma_read_cache_async2(
        [
            (key, get_ptr(dst), size),
            (key + "_not_exist", get_ptr(dst), size),
            (key + "_not_exist1", get_ptr(dst), size),
        ]
    )
    print(f"Read result: {ret}")
    assert ret == [0, -1, -1]

    assert src == dst
    rdma_conn.close()


asyncio.run(main())
