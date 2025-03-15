import infinistore
import uuid
import ctypes
import time


def generate_uuid():
    return str(uuid.uuid4())


def get_ptr(mv: memoryview):
    return ctypes.addressof(ctypes.c_char.from_buffer(mv))


config = infinistore.ClientConfig(
    host_addr="127.0.0.1",
    service_port=12345,
    log_level="warning",
    connection_type=infinistore.TYPE_TCP,
    ib_port=1,
    link_type=infinistore.LINK_ETHERNET,
    dev_name="mlx5_0",
)


def main():
    try:
        conn = infinistore.InfinityConnection(config)
        conn.connect()
        key = generate_uuid()

        size = 128 * 1024
        src = bytearray(size)
        # dst = memoryview(bytearray(100))
        for i in range(1000):
            src[i] = i % 200

        now = time.time()
        N = 1000
        for i in range(N):
            conn.tcp_write_cache(key + str(i), get_ptr(src), len(src))
        print("TCP write time taken: ", time.time() - now)

        now = time.time()
        ret = []
        for i in range(N):
            ret.append(conn.tcp_read_cache(key + str(i)))
        print("TCP read Time taken: ", time.time() - now)

        assert len(ret) == len(src)
        for i in range(len(src)):
            assert ret[i] == src[i]
    except Exception as e:
        print(e)
    finally:
        conn.close()


main()
