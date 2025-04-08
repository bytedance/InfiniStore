import uuid
from infinistore import (
    register_server,
    purge_kv_map,
    get_kvmap_len,
    ServerConfig,
    Logger,
    evict_cache,
    ConsulClusterMgr,
    TYPE_RDMA,
)
import asyncio
import uvloop
from fastapi import FastAPI
import uvicorn
import argparse
import logging
import os
import json
from fastapi.responses import JSONResponse, Response

# disable standard logging, we will use our own logger
logging.disable(logging.INFO)

app = FastAPI()
config: ServerConfig = None


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


@app.get("/health")
async def health():
    Logger.info(f"Health check received at {config.host}:{config.manage_port}...")
    return Response(content="Healthy", status_code=200)


@app.get("/service/config")
async def service_config() -> Response:
    """
    Query the configuration about how to connect to this server node

    Response:
    {
        "connection_type": "TYPE_RDMA",
        "ib_port": "1",
        "link_type": "LINK_ETHERNET",
        "dev_name": "mlx5_0"
    }
    """
    service_conf = {
        "manage_port": config.manage_port,
        "service_port": config.service_port,
        "connection_type": TYPE_RDMA,
        "ib_port": config.ib_port,
        "link_type": config.link_type,
        "dev_name": config.dev_name,
    }
    return JSONResponse(status_code=200, content=service_conf)


def get_parser():
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
        "--evict-interval",
        required=False,
        default=5,
        help="evict interval, default 5s",
    )
    parser.add_argument(
        "--evict-min-threshold",
        required=False,
        default=0.6,
        help="evict min threshold, default 0.6",
    )
    parser.add_argument(
        "--evict-max-threshold",
        required=False,
        default=0.8,
        help="evict max threshold, default 0.8",
    )
    parser.add_argument(
        "--enable-periodic-evict",
        required=False,
        action="store_true",
        default=False,
        help="enable evict cache, default False",
    )
    parser.add_argument(
        "--hint-gid-index",
        required=False,
        default=-1,
        help="hint gid index, default 1, -1 means no hint",
        type=int,
    )
    parser.add_argument(
        "--cluster-mode",
        required=False,
        action="store_true",
        help="Specify whether the infinistore server is in a cluster",
        dest="cluster_mode",
    )
    parser.add_argument(
        "--bootstrap-ip",
        required=False,
        default="127.0.0.1:18080",
        help="The bootstrap ip:port address to query for cluster information",
        type=str,
        dest="bootstrap_ip",
    )
    parser.add_argument(
        "--service-id",
        required=True,
        default="infinistore-standalone",
        help="The service ID which is used by consul cluster to identify the service instance",
        type=str,
        dest="service_id",
    )

    return parser


def prevent_oom():
    pid = os.getpid()
    with open(f"/proc/{pid}/oom_score_adj", "w") as f:
        f.write("-1000")


async def periodic_evict(min_threshold: float, max_threshold: float, interval: int):
    while True:
        evict_cache(min_threshold, max_threshold)
        await asyncio.sleep(interval)


def main():
    global config

    parser = get_parser()
    args = parser.parse_args()
    config = ServerConfig(
        **vars(args),
    )
    config.verify()

    Logger.set_log_level(config.log_level)
    Logger.info(config)

    loop = uvloop.new_event_loop()
    asyncio.set_event_loop(loop)
    # 16 GB pre allocated
    # TODO: find the minimum size for pinning memory and ib_reg_mr
    register_server(loop, config)

    if args.enable_periodic_evict:
        loop.create_task(
            periodic_evict(
                config.evict_min_threshold,
                config.evict_max_threshold,
                config.evict_interval,
            )
        )
    prevent_oom()

    Logger.info("set oom_score_adj to -1000 to prevent OOM")

    http_config = uvicorn.Config(
        app, host="0.0.0.0", port=config.manage_port, loop="uvloop"
    )

    if args.cluster_mode:
        # Initialized the cluster mgr with a bootstrap ip:port
        health_url = f"http://{args.host}:{config.manage_port}/health"
        cluster_mgr = ConsulClusterMgr(bootstrap_address=args.bootstrap_ip)

        # Note: service_id is required by consul cluster to uniquely identify a service instance
        cluster_mgr.register_service_node(
            service_host=args.host,
            service_port=config.service_port,
            service_id=args.service_id,
            service_manage_port=config.manage_port,
            check={"http": health_url, "interval": "5s"},
        )
        loop.create_task(cluster_mgr.refresh_task())

    server = uvicorn.Server(http_config)

    Logger.warn("server started")
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
