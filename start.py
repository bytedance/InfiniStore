import infinity
import asyncio
import uvloop
import fastapi
from fastapi import FastAPI, Request
import uvicorn
import torch
from pydantic import BaseModel




app = FastAPI()

class KeyOpStatusRequest(BaseModel):
    key: str

class KeyOpStatusResponse(BaseModel):
    status: int


@app.get("/status")
async def status():
    return {"Hello": "World"}

@app.get("/kvmapSize")
async def read_status():
    return infinity._infinity.get_kvmap_len()

@app.get("/key/write/{key}")
async def getKeyWriteStatus(key) -> KeyOpStatusResponse:
    return KeyOpStatusResponse(status = infinity._infinity.get_key_write_status(key))

@app.get("/key/read/{key}")
async def getKeyReadStatus(key) -> KeyOpStatusResponse:
    return KeyOpStatusResponse(status = infinity._infinity.get_key_read_status(key))


def check_p2p_access():
    num_devices = torch.cuda.device_count()
    for i in range(num_devices):
        for j in range(num_devices):
            if i != j:
                can_access = torch.cuda.can_device_access_peer(i, j)
                if can_access:
                    #print(f"Peer access supported between device {i} and {j}")
                    pass
                else:
                    print(f"Peer access NOT supported between device {i} and {j}")

if __name__ == "__main__":

    check_p2p_access()

    loop = uvloop.new_event_loop()
    asyncio.set_event_loop(loop)
    infinity.register_server(loop)
    config = uvicorn.Config(
    app,
    host="0.0.0.0",
    port=8888,
    loop="uvloop",
    log_level="warning"  # Disables logging
    )

    server = uvicorn.Server(config)

    # 运行服务器
    loop.run_until_complete(server.serve())