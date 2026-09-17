from infinistore import (
    ClientConfig,
    Logger,
    InfinityConnection,
)
import infinistore
import asyncio
import hashlib
from consul import Consul
from typing import Dict
import json
import requests
from requests.exceptions import HTTPError
from http import HTTPStatus
from dataclasses import dataclass


__all__ = ["ConsulClusterMgr", "NoClusterMgr"]


# The consistent hashing function which always hashes the same string to same integer
def sha256_hash(key: str) -> int:
    # Create a sha256 hash object
    sha256 = hashlib.sha256()
    # Update the hash object with the string (encode to bytes)
    sha256.update(key.encode("utf-8"))
    hex_digest = sha256.hexdigest()
    return int(hex_digest, 16)


@dataclass
class ServiceNode:
    host: str
    port: int
    manage_port: int
    conn: InfinityConnection


class ClusterMgrBase:
    def __init__(
        self,
        bootstrap_address: str,
        cluster_mode: bool = True,
        service_manage_port: int = 8080,
        refresh_interval=10,
    ):
        """
        Args:
            bootstrap_address (str): The initial address in ip:port format used to query cluster information
            cluster_mode (bool): whether the infinistore service runs in cluster mode (requires a consul cluster)
            service_manage_port (int): the port which service uses to provide management functionalites
        """
        self.bootstrap_ip, self.bootstrap_port = bootstrap_address.split(":")
        self.cluster_nodes = [bootstrap_address]
        self.cluster_mode = cluster_mode
        self.service_manage_port = service_manage_port
        self.service_nodes: Dict[str, ServiceNode] = {}
        self.refresh_interval = refresh_interval

    def get_cluster_info(self, cluster_node_ip: str) -> list[str]:
        """
        The function get the current alive cluster nodes in the cluster. One of the nodes will
        be chosen to send request to

        Args:
            cluster_node_ip (str): The node ip to query

        Returns:
            list[str]: The list of addresses(ip:port) of the alive nodes in the cluster
        """
        pass

    def get_service_config(self, service_host: str, service_manage_port: int) -> dict:
        """
        The function retrieves the service config parameters
        Args:
            service_host (str): The host(ip) where you can query the service config from
            service_manage_port (int): the port number(may be different with service port) of the service Web APIs
        """
        # Default values for insfinistore server config parameters
        conn_type = infinistore.TYPE_RDMA
        link_type = infinistore.LINK_ETHERNET
        dev_name = "mlx5_0"
        ib_port = 1
        service_port = 9988
        manage_port = 8080

        # The infinistore server must implement the API to provide the running parameters
        # TODO: Alternative way is registering the parameters to consul cluster, but it
        # doesn't work for the case non-cluster setup of infinistore server

        url = f"http://{service_host}:{service_manage_port}/service/config"
        with requests.get(url=url) as resp:
            if resp.status_code == HTTPStatus.OK:
                json_data = json.loads(resp.json())
                manage_port = json_data["manage_port"]
                conn_type = json_data["connection_type"]
                link_type = json_data["link_type"]
                dev_name = json_data["dev_name"]
                ib_port = json_data["ib_port"]
                service_port = int(json_data["service_port"])

        return {
            "manage_port": manage_port,
            "connection_type": conn_type,
            "link_type": link_type,
            "dev_name": dev_name,
            "ib_port": ib_port,
            "service_port": service_port,
        }

    def refresh_service_nodes(self, service_name: str = "infinistore") -> bool:
        """
        The function refresh the alive nodes which have infinistore servers running
        Currently only infinistore service is supported(tested)
        """
        pass

    def register_service_node(
        self,
        service_id: str = None,
        service_name: str = "infinistore",
        service_host: str = "",
        service_port: int = 12345,
        service_manage_port: int = 8080,
        check: dict = None,
    ) -> bool:
        """
        The function is called by a service node to register itself to the cluster
        service_id is uniquely identify a running instance of the service

        Args:
            service_id (str): The unique ID of the service instance
            service_name (str): str="infinistore",
            service_host (str): IP address of the host where the server is running on
            service_port (int): The service port which provides domain APIs
            service_manage_port (int): The port number which provides management APIs
            check:dict check is a dict struct which contains (http|tcp|script and interval fields)
        Returns:
            bool: If the register success or exists, return true. Otherwise return false
        """
        pass

    def deregister_service(self, service_id: str = None):
        """
        The function is called to deregister a service id

        Args:
            service_id (str): The unique ID of the service instance
        Returns:
            bool: If the deregister success, return true. Otherwise return false
        """
        pass

    def refresh_cluster(self):
        """
        The function refresh the alive nodes of the cluster
        """
        # If not in cluster mode, do nothing
        if not self.cluster_mode:
            return
        for node_ip in self.cluster_nodes:
            try:
                updated_nodes = self.get_cluster_info(node_ip)
                if len(updated_nodes) != 0:
                    self.cluster_nodes = updated_nodes
                    # A non-empty list indicates a working node, so no need to query further
                    break
            except Exception:
                Logger.warn(f"Cannot refresh cluster info from {node_ip}")
                # Check next node if something wrong with this node
                continue

    async def refresh_task(self):
        """
        Task function to refresh cluster periodically
        """
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, self.refresh_cluster)
            await loop.run_in_executor(None, self.refresh_service_nodes)
            await asyncio.sleep(self.refresh_interval)

    def setup_connection(
        self, service_host: str, service_port: int, service_manage_port: int
    ) -> bool:
        """
        The function setup a connection to an infinistore service instance
        Args:
            service_host (str): The host(ip) to connect to
            service_port (int): The port number the infinistore service is running at
            service_manage_port (int): The port number the infinistore web server is running at
        """
        try:
            service_config = self.get_service_config(
                service_host=service_host, service_manage_port=service_manage_port
            )
        except Exception as ex:
            Logger.warn(
                f"Cannot get service config for {service_host}:{service_port}, exception: {ex} "
            )
            return False

        config = ClientConfig(
            host_addr=service_host,
            service_port=int(service_port),
            log_level="info",
            connection_type=service_config["connection_type"],
            ib_port=service_config["ib_port"],
            link_type=service_config["link_type"],
            dev_name=service_config["dev_name"],
        )
        service_node = ServiceNode(
            host=service_host,
            port=service_port,
            manage_port=service_config["manage_port"],
            conn=infinistore.InfinityConnection(config),
        )
        service_key = f"{service_host}:{service_port}"
        self.service_nodes[service_key] = service_node
        return True

    def get_connection(self, key: str = None) -> InfinityConnection:
        """
        The function chooses an infinistore service connection
        based upon a query key. If no key is specified, return the first
        available connection

        Args:
            key (str, optional): The key to choose service node

        Returns:
            InfinityConnection: The connection to infinistore server node
        """
        if len(self.service_nodes) == 0:
            Logger.warn(
                "There are no live nodes in the cluster, forgot to register the service node?"
            )
            return None

        # Default to choose the first one
        k = 0 if key is None else sha256_hash(key) % len(self.service_nodes)

        # Retrieve the service connection based upon the service address
        keys = list(self.service_nodes.keys())
        service_node = self.service_nodes[keys[k]]
        if service_node.conn is None:
            ok = self.setup_connection(
                service_host=service_node.host,
                service_port=service_node.port,
                service_manage_port=service_node.manage_port,
            )
            if not ok:
                return None

        assert self.service_nodes[keys[k]].conn is not None
        return self.service_nodes[keys[k]].conn


class ConsulClusterMgr(ClusterMgrBase):
    def __init__(self, bootstrap_address: str, service_manage_port: int = 8080):
        super().__init__(
            bootstrap_address=bootstrap_address, service_manage_port=service_manage_port
        )

    def get_consul(self, cluster_node_ip: str) -> Consul:
        consul_ip, consul_port = cluster_node_ip.split(":")
        return Consul(host=consul_ip, port=consul_port)

    def get_cluster_info(self, cluster_node_ip: str) -> list[str]:
        updated_cluster_nodes: list[str] = []
        consul = self.get_consul(cluster_node_ip)
        try:
            members = consul.agent.members()
            for member in members:
                # member['Port'] is the port which the consul agents communicate
                # not the port which can be queries for members, so change it to bootstrap port
                updated_cluster_nodes.append(f"{member['Addr']}:{self.bootstrap_port}")
        except Exception as ex:
            Logger.error(
                f"Could not get cluster info from {cluster_node_ip}, exception: {ex}"
            )

        return updated_cluster_nodes

    def get_service_status(self, service_name: str = "infinistore"):
        # Deregister the service nodes which are not healthy
        failed_services = []
        live_services = []
        for cluster_node_ip in self.cluster_nodes:
            consul = self.get_consul(cluster_node_ip)
            _, service_checks = consul.health.service(service_name)

            # We got a list of service nodes, no need to try further
            if len(service_checks) > 0:
                break

        if service_checks:
            for service_check in service_checks:
                service = service_check["Service"]
                if service["Service"] != service_name:
                    continue
                for i in range(len(service_check["Checks"])):
                    check = service_check["Checks"][i]
                    if check["ServiceName"] != service_name:
                        continue
                    if check["Status"] == "critical":
                        self.deregister_service(service["ID"])
                        failed_services.append(service)
                    else:
                        live_services.append(service)
        return live_services, failed_services

    def refresh_service_nodes(self, service_name: str = "infinistore"):
        refresh_services = {}
        Logger.info("Refresh service nodes for {service_name}...")
        # Get the registered service nodes
        for cluster_node_ip in self.cluster_nodes:
            consul = self.get_consul(cluster_node_ip)
            _, registered_services = consul.catalog.service(service_name)
            # We got a list of service nodes, no need to try further
            if len(registered_services) > 0:
                break

        # Get the service_manage_port (in tags) and put them into dict key service_host:service_port
        for service in registered_services:
            key = f"{service['ServiceAddress']}:{service['ServicePort']}"
            for tag in service["ServiceTags"]:
                if tag.startswith("service_manage_port"):
                    service_manage_port = tag.split("=")[1]
            refresh_services[key] = service_manage_port

        # Remove the services which are not in the live node list
        # from service_nodes
        for service_key in self.service_nodes:
            if service_key not in refresh_services:
                service_node = self.service_nodes.pop(service_key)
                if service_node.conn is not None:
                    service_node.conn.close()

        # Add the new services(which are not in the current service node list)
        for s in refresh_services:
            # We don't support update operation for now.
            Logger.info(f"Service node {s} added")
            if s in self.service_nodes:
                continue

            service_host, service_port = s.split(":")
            service_node = ServiceNode(
                host=service_host,
                port=service_port,
                manage_port=refresh_services[s],
                conn=None,
            )
            self.service_nodes[s] = service_node

    def register_service_node(
        self,
        service_id: str = "infinistore",
        service_name: str = "infinistore",
        service_host: str = "",
        service_port: int = 12345,
        service_manage_port: int = 8080,
        check: dict = None,
    ) -> bool:
        ret = True
        try:
            # Create a Consul client
            consul = self.get_consul(self.cluster_nodes[0])

            # Register the service with Consul
            consul.agent.service.register(
                name=service_name,
                service_id=service_id,
                address=service_host,
                port=service_port,
                tags=[f"service_manage_port={service_manage_port}"],
                check={
                    "http": check["http"],
                    "interval": check["interval"],
                    "timeout": "5s",
                },
                timeout="5s",
            )
        except HTTPError as ex:
            # Check for 409 Conflict if the service already exists
            if ex.response.status_code == 409:
                Logger.warn(f"Service {service_name} already exists.")
            else:
                ret = False
                Logger.error(
                    f"Error registering service {service_name}, exception: {ex}"
                )

        return ret

    def deregister_service(self, service_id: str):
        ret = True
        try:
            # Create a Consul client
            consul = self.get_consul(self.cluster_nodes[0])

            # Deregister the service with Consul
            consul.agent.service.deregister(service_id)
        except HTTPError as ex:
            ret = False
            Logger.error(f"Error deregistering service {service_id}, exception: {ex}")

        return ret


class NoClusterMgr(ClusterMgrBase):
    def __init__(self, bootstrap_address: str, service_manage_port: int = 8080):
        super().__init__(
            bootstrap_address,
            cluster_mode=False,
            service_manage_port=service_manage_port,
        )

    def refresh_service_nodes(self, service_name: str = "infinistore"):
        # For NoCluster cluster, the service node address is
        if len(self.service_nodes) > 0:
            return
        cluster_node_ip = self.cluster_nodes[0]
        service_host, service_port = cluster_node_ip.split(":")
        # Call service to get service running arguments
        service_config = self.get_service_config(
            service_host=service_host, service_manage_port=self.service_manage_port
        )
        service_host = cluster_node_ip.split(":")[0]
        # Setup a ClientConfig
        config = ClientConfig(
            host_addr=service_host,
            service_port=service_config["service_port"],
            log_level="info",
            connection_type=service_config["connection_type"],
            ib_port=service_config["ib_port"],
            link_type=service_config["link_type"],
            dev_name=service_config["dev_name"],
        )
        service_port = service_config["service_port"]
        service_key = f"{service_host}:{service_port}"
        service_node = ServiceNode(
            host=service_host,
            port=service_port,
            manage_port=service_config["manage_port"],
            conn=infinistore.InfinityConnection(config),
        )
        self.service_nodes[service_key] = service_node

