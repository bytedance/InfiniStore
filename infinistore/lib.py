import infinistore._infinistore as _infinistore

# sphinx-doc will mock infinistore._infinistore, it has to be written like this

import os
import subprocess
import asyncio
from functools import singledispatchmethod
from typing import Optional, Union, List, Tuple
import numpy as np


# connection type: default is RDMA
TYPE_RDMA = "RDMA"
TYPE_TCP = "TCP"
# rdma link type
LINK_ETHERNET = "Ethernet"
LINK_IB = "IB"


# Define exceptions which can be caught by the client such as KeyNotFound


class InfiniStoreException(Exception):
    pass


class InfiniStoreKeyNotFound(InfiniStoreException):
    pass


class ClientConfig(_infinistore.ClientConfig):
    """
    ClientConfig is a configuration class for the Infinistore client.

    Attributes:
        connection_type (str): The type of connection to use (e.g. TYPE_RDMA).
        host_addr (str): The address of the host.
        dev_name (str): The name of the device (default is "mlx5_1").
        ib_port (int): The port number of the InfiniBand device (default is 1).
        link_type (str): The type of link (default is "IB").
        service_port (int): The port number of the service.
        log_level (str): The logging level (default is "warning").
    """

    def __init__(self, **kwargs):
        super().__init__()
        self.connection_type = kwargs.get("connection_type", None)
        self.host_addr = kwargs.get("host_addr", None)
        self.dev_name = kwargs.get("dev_name", "mlx5_1")
        self.ib_port = kwargs.get("ib_port", 1)
        self.link_type = kwargs.get("link_type", "IB")
        self.service_port = kwargs.get("service_port", None)
        # get log from system env
        # if log level is not set in Config and system env is not set either, use warning as default
        if "INFINISTORE_LOG_LEVEL" in os.environ:
            self.log_level = os.environ["INFINISTORE_LOG_LEVEL"]
        else:
            self.log_level = kwargs.get("log_level", "warning")

    def __repr__(self):
        return (
            f"ServerConfig(service_port={self.service_port}, "
            f"log_level='{self.log_level}', host_addr='{self.host_addr}', "
            f"connection_type='{self.connection_type.name}')"
            f"dev_name='{self.dev_name}', ib_port={self.ib_port}, link_type='{self.link_type}'"
        )

    def verify(self):
        if self.connection_type not in [TYPE_RDMA, TYPE_TCP]:
            raise Exception("Invalid connection type")
        if self.host_addr == "":
            raise Exception("Host address is empty")
        if self.service_port == 0:
            raise Exception("Service port is 0")
        if self.log_level not in ["error", "debug", "info", "warning"]:
            raise Exception("log level should be error, debug, info or warning")
        if self.ib_port < 1:
            raise Exception("ib port of device should be greater than 0")
        if self.connection_type == TYPE_RDMA and self.link_type not in [
            "IB",
            "Ethernet",
        ]:
            raise Exception("link type should be IB or Ethernet for RDMA connection")


class ServerConfig(_infinistore.ServerConfig):
    class ServerConfig:
        """
        ServerConfig is a configuration class for the server settings.

        Attributes:
            manage_port (int): The port used for management. Defaults to 0.
            service_port (int): The port used for service. Defaults to 0.
            log_level (str): The logging level. Defaults to "warning".
            dev_name (str): The device name. Defaults to "mlx5_1".
            ib_port (int): The InfiniBand port number. Defaults to 1.
            link_type (str): The type of link. Defaults to "IB".
            prealloc_size (int): The preallocation size. Defaults to 16.
            minimal_allocate_size (int): The minimal allocation size. Defaults to 64.
            auto_increase (bool): indicate if infinistore will be automatically increased. 10GB each time. Default False.
        """

    def __init__(self, **kwargs):
        super().__init__()
        self.manage_port = kwargs.get("manage_port", 0)
        self.service_port = kwargs.get("service_port", 0)
        self.log_level = kwargs.get("log_level", "warning")
        self.dev_name = kwargs.get("dev_name", "mlx5_1")
        self.ib_port = kwargs.get("ib_port", 1)
        self.link_type = kwargs.get("link_type", "IB")
        self.prealloc_size = kwargs.get("prealloc_size", 16)
        self.minimal_allocate_size = kwargs.get("minimal_allocate_size", 64)
        self.auto_increase = kwargs.get("auto_increase", False)
        self.evict_min_threshold = kwargs.get("evict_min_threshold", 0.6)
        self.evict_max_threshold = kwargs.get("evict_max_threshold", 0.8)
        self.evict_interval = kwargs.get("evict_interval", 5)

    def __repr__(self):
        return (
            f"ServerConfig: service_port={self.service_port}, manage_port={self.manage_port}, "
            f"log_level='{self.log_level}', "
            f"dev_name='{self.dev_name}', ib_port={self.ib_port}, link_type='{self.link_type}', "
            f"prealloc_size={self.prealloc_size}, minimal_allocate_size={self.minimal_allocate_size}, "
            f"auto_increase={self.auto_increase}, evict_min_threshold={self.evict_min_threshold}, "
            f"evict_max_threshold={self.evict_max_threshold}, evict_interval={self.evict_interval}"
        )

    def verify(self):
        if self.service_port == 0:
            raise Exception("Service port is 0")
        if self.manage_port == 0:
            raise Exception("Manage port is 0")
        if self.log_level not in ["error", "debug", "info", "warning"]:
            raise Exception("log level should be error, debug, info or warning")
        if self.ib_port < 1:
            raise Exception("ib port of device should be greater than 0")
        if self.link_type not in ["IB", "Ethernet"]:
            raise Exception("link type should be IB or Ethernet")
        if self.minimal_allocate_size < 16:
            raise Exception("minimal allocate size should be greater than 16")


class Logger:
    @staticmethod
    def info(msg):
        _infinistore.log_msg("info", str(msg))

    @staticmethod
    def debug(msg):
        _infinistore.log_msg("debug", str(msg))

    @staticmethod
    def error(msg):
        _infinistore.log_msg("error", str(msg))

    @staticmethod
    def warn(msg):
        _infinistore.log_msg("warning", str(msg))

    @staticmethod
    def set_log_level(level):
        _infinistore.set_log_level(level)


def get_kvmap_len():
    """
    Returns the length of the key-value map in the infinistore.

    This function calls the underlying _infinistore.get_kvmap_len() method to
    get the length of the key-value map.

    Returns:
        The result of the _infinistore.get_kvmap_len() method call.
    """
    return _infinistore.get_kvmap_len()


def purge_kv_map():
    """
    Purges the key-value map in the infinistore.

    This function calls the underlying _infinistore.purge_kv_map() method to
    clear all entries in the key-value map, effectively resetting it.

    Returns:
        The result of the _infinistore.purge_kv_map() method call.
    """
    return _infinistore.purge_kv_map()


def register_server(loop, config: ServerConfig):
    """
    Registers a server with the given event loop and configuration.

    This function is intended to be used internally and should not be called by clients directly.

    Args:
        loop: The event loop to register the server with.
        config (ServerConfig): The configuration for the server.

    Raises:
        Exception: If the server registration fails.
    """
    # client does not need to call this function
    from uvloop.loop import libuv_get_loop_t_ptr
    import ctypes
    from ctypes import pythonapi, c_void_p, py_object

    PyCapsule_GetPointer = pythonapi.PyCapsule_GetPointer
    PyCapsule_GetPointer.restype = c_void_p
    PyCapsule_GetPointer.argtypes = [py_object, ctypes.c_char_p]
    loop_ptr = PyCapsule_GetPointer(libuv_get_loop_t_ptr(loop), None)

    # from cpython.pycapsule import PyCapsule_GetPointer
    # <uint64_t>PyCapsule_GetPointer(obj, NULL)
    if _infinistore.register_server(loop_ptr, config) < 0:
        raise Exception("Failed to register server")


def evict_cache(min_threshold: float, max_threshold: float):
    """
    Evicts the cache in the infinistore.

    This function calls the underlying _infinistore.evict_cache() method to
    clear all entries in the cache, effectively resetting it.

    Returns:
        The result of the _infinistore.evict_cache() method call.
    """
    if min_threshold >= max_threshold:
        raise Exception("min_threshold should be less than max_threshold")
    if min_threshold > 1 or min_threshold < 0:
        raise Exception("min_threshold should be in (0, 1)")
    if max_threshold > 1 or max_threshold < 0:
        raise Exception("max_threshold should be in (0, 1)")

    return _infinistore.evict_cache(min_threshold, max_threshold)


def _kernel_modules():
    modules = set()
    try:
        with open("/proc/modules", "r") as f:
            for line in f:
                sep = line.find(" ")
                if sep != -1:
                    modules.add(line[:sep])
    except IOError as e:
        raise Exception(f"can not read /proc/modules: {e}")
    return modules


def _check_rdma_devices_ibv():
    try:
        result = subprocess.run(
            ["ibv_devinfo"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if result.returncode != 0:
            return
        output = result.stdout
        devices = output.split("\n\n")
        port_active = False
        for device_info in devices:
            if "hca_id" in device_info:
                if "PORT_ACTIVE" in device_info:
                    port_active = True
                    break
        if port_active is False:
            raise Exception("No active RDMA device found")
    except FileNotFoundError:
        raise Exception(
            "command ibv_devinfo not found, make sure RDMA tools are installed; for ubuntu, run apt install ibv_devinfo"
        )


class InfinityConnection:
    """
    A class to manage connections and data transfers with an Infinistore instance using RDMA connections.

    Attributes:
        conn (_infinistore.Connection): The connection object to the Infinistore instance.
        rdma_connected (bool): Indicates if connected to a remote instance via RDMA.
        config (ClientConfig): Configuration object for the connection.
    """

    OP_RDMA_READ = "A"

    def __init__(self, config: ClientConfig):
        config.verify()
        self.conn = _infinistore.Connection()
        self.rdma_connected = False
        self.config = config

        # used for async io
        self.semaphore = asyncio.BoundedSemaphore(128)
        Logger.set_log_level(config.log_level)

    async def connect_async(self):
        """
        Asynchronously establishes a connection based on the configuration.

        Raises:
            Exception: If the initialization of the remote connection fails.
            Exception: If the setup of the RDMA connection fails.

        Logs:
            A warning indicating that the async connect may have bugs.

        This method runs the blocking connection setup in an executor to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()

        def blocking_connect():
            if self.conn.init_connection(self.config) < 0:
                raise Exception("Failed to initialize remote connection")
            if self.config.connection_type == TYPE_RDMA:
                if self.conn.setup_rdma(self.config) < 0:
                    raise Exception("Failed to setup RDMA connection")
                self.rdma_connected = True

        await loop.run_in_executor(None, blocking_connect)

    def connect(self):
        """
        Establishes a connection to the Infinistore instance based on the configuration.

        Raises:
            Exception: If already connected to a remote instance.
            Exception: If failed to initialize remote connection.
            Exception: If failed to setup RDMA connection.
        """
        if self.rdma_connected:
            raise Exception("Already connected to remote instance")

        print(f"connecting to {self.config.host_addr}")
        ret = self.conn.init_connection(self.config)
        if ret < 0:
            raise Exception("Failed to initialize remote connection")

        if self.config.connection_type == TYPE_RDMA:
            ret = self.conn.setup_rdma(self.config)
            if ret < 0:
                raise Exception(f"Failed to write to infinistore, ret = {ret}")
            self.rdma_connected = True

    def close(self):
        """
        Closes the connection to the Infinistore instance.
        """
        self.conn.close()

    def tcp_read_cache(self, key: str, **kwargs) -> np.ndarray:
        """
        Retrieve a single cached item from the TCP connection.

        Parameters:
        key (str): The key associated with the cached item.
        **kwargs: Additional keyword arguments.

        Returns:
        np.ndarray: The cached item retrieved from the TCP connection.
        """
        return self.conn.r_tcp(key)

    def tcp_write_cache(self, key: str, ptr: int, size: int, **kwargs):
        """
        Writes a single cache entry to the remote memory using TCP.

        Args:
            key (str): The key of the cache entry to write.
            ptr (int): The pointer to the memory location where the data should be written.
            size (int): The size of the data to write.
            **kwargs: Additional keyword arguments.

        Raises:
            Exception: If the key is empty.
            Exception: If the size is 0.
            Exception: If the pointer is 0.
            Exception: If the write operation fails.
        """
        if key == "":
            raise Exception("key is empty")
        if size == 0:
            raise Exception("size is 0")
        if ptr == 0:
            raise Exception("ptr is 0")
        ret = self.conn.w_tcp(key, ptr, size)
        if ret < 0:
            raise Exception(f"Failed to write to infinistore, ret = {ret}")

    async def rdma_write_cache_async(
        self, blocks: List[Tuple[str, int]], block_size: int, ptr: int
    ):
        if not self.rdma_connected:
            raise Exception("this function is only valid for connected rdma")

        await self.semaphore.acquire()
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        keys, offsets = zip(*blocks)

        def _callback(code):
            if code != 200:
                loop.call_soon_threadsafe(
                    future.set_exception,
                    Exception(f"Failed to write to infinistore, ret = {code}"),
                )
            else:
                loop.call_soon_threadsafe(future.set_result, code)
            self.semaphore.release()

        ret = self.conn.w_rdma_async(
            keys,
            offsets,
            block_size,
            ptr,
            _callback,
        )
        if ret < 0:
            raise Exception(f"Failed to write to infinistore, ret = {ret}")
        return await future

    async def rdma_read_cache_async(
        self, blocks: List[Tuple[str, int]], block_size: int, ptr: int
    ):
        if not self.rdma_connected:
            raise Exception("this function is only valid for connected rdma")
        pass

        await self.semaphore.acquire()
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def _callback(code):
            if code == 404:
                loop.call_soon_threadsafe(
                    future.set_exception, InfiniStoreKeyNotFound("some keys not found")
                )
            elif code != 200:
                loop.call_soon_threadsafe(
                    future.set_exception,
                    Exception(f"Failed to read to infinistore, ret = {code}"),
                )
            else:
                loop.call_soon_threadsafe(future.set_result, code)
            self.semaphore.release()

        keys, offsets = zip(*blocks)
        ret = self.conn.r_rdma_async(
            keys,
            offsets,
            block_size,
            ptr,
            _callback,
        )
        if ret < 0:
            raise Exception(f"Failed to read to infinistore, ret = {ret}")
        return await future

    def check_exist(self, key: str):
        """
        Check if a given key exists in the store.

        Args:
            key (str): The key to check for existence.

        Returns:
            bool: True if the key exists, False otherwise.

        Raises:
            Exception: If there is an error checking the key's existence.
        """
        ret = self.conn.check_exist(key)
        if ret < 0:
            raise Exception("Failed to check if this key exists")
        return True if ret == 0 else False

    def get_match_last_index(self, keys: List[str]):
        """
        Retrieve the last index of a match for the given keys.

        Args:
            keys (List[str]): A list of string keys to search for matches.

        Returns:
            int: The last index of a match.

        Raises:
            Exception: If no match is found (i.e., if the return value is negative).
        """
        ret = self.conn.get_match_last_index(keys)
        if ret < 0:
            raise Exception("can't find a match")
        return ret

    @singledispatchmethod
    def register_mr(self, arg: Union[int], size: Optional[int] = None):
        """
        Registers a memory region (MR) for the given argument.

        Args:
            arg (Union[int]): The argument for which the memory region is to be registered.
            size (Optional[int], optional): The size of the memory region to be registered. Defaults to None.

        Raises:
            NotImplementedError: If the type of the argument is not supported.
        """
        raise NotImplementedError(f"not supported: {type(arg)}")

    @register_mr.register
    def _(self, ptr: int, size):
        """
        Registers a memory region (MR) for an integer pointer.

        Args:
            ptr (int): The pointer to the memory region.
            size (int): The size of the memory region.

        Raises:
            Exception: If the RDMA connection is not established.
            Exception: If the memory region registration fails.

        Returns:
            int: The result of the memory region registration.
        """
        if not self.rdma_connected:
            raise Exception("this function is only valid for connected rdma")

        ret = self.conn.register_mr(ptr, size)
        if ret < 0:
            raise Exception("register memory region failed")
        return ret

    def delete_keys(self, keys: List[str]):
        """
        Delete a list of keys

        Args:
            keys (List[str]): The list of string keys to delete

        Returns:
            int: The count of the deleted keys

        Raises:
            Exception: If there is something wrong(return value is -1)
        """
        ret = self.conn.delete_keys(keys)
        if ret < 0:
            raise Exception(
                "somethings are wrong, not all the specified keys were deleted"
            )
        return ret
