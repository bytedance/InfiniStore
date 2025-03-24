import uuid
from infinistore import (
    register_server,
    purge_kv_map,
    get_kvmap_len,
    ServerConfig,
    Logger,
)
import asyncio
import uvloop
from fastapi import FastAPI
import uvicorn
import argparse
import logging
import os


# disable standard logging, we will use our own logger
logging.disable(logging.INFO)

app = FastAPI()


@app.post("/purge")
async def purge():
    Logger.info("clear kvmap")
    num = get_kvmap_len()
    purge_kv_map()
    return {"status": "ok", "num": num}


def generate_uuid():
    return str(uuid.uuid4())


@app.get("/kvmap_len")
async def kvmap_len():
    return {"len": get_kvmap_len()}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--auto-increase",
        required=False,
        action="store_true",
        help="increase allocated memory automatically, 10GB each time, default False",
    )
    parser.add_argument(
        "--host",
        required=False,
        help="listen on which host, default 0.0.0.0",
        default="0.0.0.0",
        type=str,
    )
    parser.add_argument(
        "--manage-port",
        required=False,
        type=int,
        default=18080,
        help="port for control plane, default 18080",
    )
    parser.add_argument(
        "--service-port",
        required=False,
        type=int,
        default=22345,
        help="port for data plane, default 22345",
    )

    parser.add_argument(
        "--log-level",
        required=False,
        default="info",
        help="log level, default warning",
        type=str,
    )

    parser.add_argument(
        "--prealloc-size",
        required=False,
        type=int,
        default=16,
        help="prealloc mem pool size, default 16GB, unit: GB",
    )
    parser.add_argument(
        "--dev-name",
        required=False,
        default="mlx5_1",
        help="Use IB device <dev> (default first device found)",
        type=str,
    )
    parser.add_argument(
        "--ib-port",
        required=False,
        type=int,
        default=1,
        help="use port <port> of IB device (default 1)",
    )
    parser.add_argument(
        "--link-type",
        required=False,
        default="IB",
        help="IB or Ethernet, default IB",
        type=str,
    )
    parser.add_argument(
        "--minimal-allocate-size",
        required=False,
        default=64,
        help="minimal allocate size, default 64, unit: KB",
        type=int,
    )
    parser.add_argument(
        "--num-stream",
        required=False,
        default=1,
        help="(deprecated)number of streams, default 1, can only be 1, 2, 4",
        type=int,
    )

    return parser.parse_args()


def prevent_oom():
    pid = os.getpid()
    with open(f"/proc/{pid}/oom_score_adj", "w") as f:
        f.write("-1000")


def main():
    args = parse_args()
    config = ServerConfig(
        manage_port=args.manage_port,
        service_port=args.service_port,
        log_level=args.log_level,
        prealloc_size=args.prealloc_size,
        dev_name=args.dev_name,
        ib_port=args.ib_port,
        link_type=args.link_type,
        minimal_allocate_size=args.minimal_allocate_size,
        num_stream=args.num_stream,
        auto_increase=args.auto_increase,
    )
    config.verify()

    Logger.set_log_level(config.log_level)
    Logger.info(config)

    loop = uvloop.new_event_loop()
    asyncio.set_event_loop(loop)
    # 16 GB pre allocated
    # TODO: find the minimum size for pinning memory and ib_reg_mr
    register_server(loop, config)

    prevent_oom()
    Logger.info("set oom_score_adj to -1000 to prevent OOM")

    http_config = uvicorn.Config(
        app, host="0.0.0.0", port=config.manage_port, loop="uvloop"
    )

    server = uvicorn.Server(http_config)

    Logger.warn("server started")
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
