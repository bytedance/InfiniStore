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
import hashlib
from requests.exceptions import HTTPError
from http import HTTPStatus
from dataclasses import dataclass


__all__ = ['ConsulClusterMgr', 'NoClusterMgr']

# The consistent hashing function(the same string is always hashed to 
# the same integer)
def sha256_hash(key: str)->int:
    # Create a sha256 hash object
    sha256 = hashlib.sha256()
    
    # Update the hash object with the string (encode to bytes)
    sha256.update(key.encode('utf-8'))    
    hex_digest=sha256.hexdigest()
    # Convert and return the integer
    return int(hex_digest, 16)

@dataclass
class ServiceNode:
    host: str
    port: int
    manage_port: int
    conn: InfinityConnection

class ClusterMgrBase():
    def __init__(self, bootstrap_address: str, cluster_mode: bool=True, service_manage_port: int=8080):
        """
        Args:
            bootstrap_address (str): The initial address in ip:port format to query cluster information
            cluster_mode (bool): whether the "cluster" is real
            service_manage_port (int): the port which service uses to provide management functionalites
        """
        self.bootstrap_ip, self.bootstrap_port = bootstrap_address.split(":")
        self.cluster_nodes = [bootstrap_address]
        self.cluster_mode = cluster_mode
        self.service_manage_port = service_manage_port
        self.service_nodes: Dict[str, ServiceNode] = {}
        self.service_id = None


    def get_cluster_info(self, cluster_node_ip: str)->list[str]:
        """
        The function get the current alive cluster nodes in the cluster. One of the nodes will
        be chosen to send request to
        
        Args:
            cluster_node_ip (str): The node ip to query 
            
        Returns:
            list[str]: The list of addresses(ip:port) of the alive nodes in the cluster
        """
        pass
    
    
    def get_service_config(self, service_host:str, service_manage_port:int)->dict:
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
        service_port = 12345
        manage_port=8080
        
        # The infinistore server must implement the API to provide the running parmaters
        # TODO: Alternative way is registering the parameters to consul cluster, but it 
        # doesn't work for the case non-cluster setup of infinistore server
        
        url = f"http://{service_host}:{service_manage_port}/service_config"
        with requests.get(url = url) as resp:
            if resp.status_code == HTTPStatus.OK:
                json_data = json.loads(resp.json())
                manage_port = json_data["manage_port"]
                conn_type = json_data["connection_type"]
                link_type = json_data["link_type"]
                dev_name = json_data["dev_name"]
                ib_port = json_data["ib_port"]
                service_port=int(json_data["service_port"])

        return {
            "manage_port": manage_port,
            "connection_type": conn_type,
            "link_type": link_type,
            "dev_name": dev_name,
            "ib_port": ib_port,
            "service_port": service_port
            }


    def refresh_service_nodes(self, service_name: str="infinistore")->bool:
        """
        The function refresh the alive nodes which have infinistore servers running
        Currently only infinistore service is supported(tested)
        """
        pass
    
            
    def register_service_node(self, 
                              service_id: str= None, 
                              service_name: str="infinistore", 
                              service_host: str="", 
                              service_port:int=12345,
                              service_manage_port: int=8080,
                              check: dict=None)->bool:
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
    
    
    def deregister_service(self, service_id: str=None):
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
        The function refresh the alive nodes of the cluster (which can be quired for service nodes)
        """
        # if not in cluster mode, do nothing
        if not self.cluster_mode:
            return
        
        for node_ip in self.cluster_nodes:
            try:
                updated_nodes = self.get_cluster_info(node_ip)
                # a non-empty list returned indicates a working node, so no need to query further
                if len(updated_nodes) != 0:
                    self.cluster_nodes = updated_nodes
                    break
            except Exception as ex:
                Logger.error(f"Cannot refresh cluster info from {node_ip}")
                # Check next node if something wrong with this node
                continue
            
    async def refresh_task(self):
        while True:
            self.refresh_cluster()
            await asyncio.sleep(10)
            
    def setup_connection(self, service_host: str, service_port: int, service_manage_port: int):
        """
        The function setup a infinistore connection to service_host:service_port
        Args:
            service_host (str): The host(ip) to connect to
            service_port (int): The port number the infinistore service is running at
            service_manage_port (int): The port number the infinistore web server is running at
        """
        service_config = self.get_service_config(service_host=service_host, service_manage_port=service_manage_port)
        config = ClientConfig(
            host_addr=service_host,
            service_port=int(service_port),
            log_level="info",
            connection_type=service_config["connection_type"],
            ib_port=service_config["ib_port"],
            link_type=service_config["link_type"],
            dev_name=service_config["dev_name"],
        )
        
        service_key = f"{service_host}:{service_port}"
        service_node = ServiceNode(
            host=service_host,
            port=service_port,
            manage_port=service_config['manage_port'],
            conn= infinistore.InfinityConnection(config)
        )
        self.service_nodes[service_key] = service_node
        
            
    def get_connection(self, key: str=None)->InfinityConnection:
        """
        The function chooses a service connection (here is infinistore) 
        based upon a query key. If no key is specified, return the first
        available connection
        
        Args:
            key (str, optional): The key to choose service node

        Returns:
            InfinityConnection: The connecttion to infinistore server node
        """
        if len(self.service_nodes) == 0:
            Logger.warn("There are no live nodes in the cluster, forgot to register ther service node?")
            return None
                
        k = 0
        # if a key is specified, hash the key to an index
        if key is not None:        
            k = sha256_hash(key) % len(self.service_nodes)
            
        # Retrieve the service connection based upon the service address
        keys = list(self.service_nodes.keys())
        service_node = self.service_nodes[keys[k]]
        if service_node.conn is None:
            self.setup_connection(service_host=service_node.host, service_port=service_node.port, service_manage_port=service_node.manage_port)
            assert self.service_nodes[keys[k]].conn is not None
        return self.service_nodes[keys[k]].conn

class ConsulClusterMgr(ClusterMgrBase):
    def __init__(self, bootstrap_address: str, service_manage_port:int=8080):
        super().__init__(bootstrap_address=bootstrap_address, service_manage_port=service_manage_port)
        

    def get_consul(self, cluster_node_ip: str)->Consul:
        consul_ip, consul_port = cluster_node_ip.split(":")
        return Consul(host=consul_ip, port=consul_port)
    
    def get_cluster_info(self, cluster_node_ip: str)->list[str]: 
        updated_nodes: list[str] = []
        consul = self.get_consul(cluster_node_ip)
        try:
            members = consul.agent.members()
            for member in members:
                # member['Port'] is the port which the consul agents communicate
                # not the port which can be queries for members, so change it to bootstrap port
                updated_nodes.append(f"{member['Addr']}:{self.bootstrap_port}")
        except Exception as ex:
            Logger.error(f"Could not get cluster info from {cluster_node_ip}, exception: {ex}")
            
        return updated_nodes
    
    def refresh_service_nodes(self, service_name: str="infinistore"):
        # Get the nodes that are registered for the service
        # The 'service' function returns a list of services with their associated nodes
        refresh_services = {}
        for cluster_node_ip in self.cluster_nodes:
            consul = self.get_consul(cluster_node_ip)
            index, services = consul.catalog.service(service_name)
            # There no services, bail out
            if len(services) > 0:
                break
            
        # Get the service_manage_port (in tags) and put them into dict key bey service_host:service_port
        for service in services:
            key = f"{service['Address']}:{service['ServicePort']}"
            for tag in service['ServiceTags']:
                if tag.startswith("service_manage_port"):
                    service_manage_port = tag.split("=")[1]
            refresh_services[key] = service_manage_port
        
        # Remove the services which are not in refresh_services
        for service_key in self.service_nodes:
            if service_key not in refresh_services:
                service_node = self.service_nodes.pop(service_key)
                service_node.conn.close()
                
        # Add the new services(which are not in the current service node list)
        for s in refresh_services:
            # We don't support update operation for now. 
            if s in self.service_nodes:
                continue
            
            service_host, service_port = s.split(":")    
            service_node = ServiceNode(
                host=service_host,
                port=service_port,
                manage_port=refresh_services[s],
                conn = None
            )
            self.service_nodes[s] = service_node
                
    def register_service_node(self, 
                              service_id: str="infinistore", 
                              service_name: str="infinistore", 
                              service_host: str="", 
                              service_port:int=12345,
                              service_manage_port:int=8080,
                              check: dict = None)->bool:
        ret = True
        try:
            # Create a Consul client
            consul = self.get_consul(self.cluster_nodes[0])

            # Register the service with Consul
            consul.agent.service.register(name=service_name,
                                        service_id=service_id,
                                        address=service_host,
                                        port=service_port,
                                        tags=[f"service_manage_port={service_manage_port}"],
                                        check= {
                                            "http": check["http"],
                                            "interval": check["interval"]
                                        },
                                        timeout="5s")
        except HTTPError as ex:
            # Check for 409 Conflict if the service already exists
            if ex.response.status_code == 409:
                Logger.warn(f"Service {service_name} already exists.")
            else:
                ret = False
                Logger.error(f"Error registering service {service_name}, exception: {ex}")
        if ret:
            self.service_id = service_id
        return ret

    def deregister_service(self):
        ret = True
        try:
            # Create a Consul client
            consul = self.get_consul(self.cluster_nodes[0])

            # Deregister the service with Consul
            consul.agent.service.deregister(self.service_id)
        except HTTPError as ex:
            ret = False
            Logger.error(f"Error deregistering service {self.service_id}, exception: {ex}")
            
        if ret:    
            self.service_id = None
        return ret

class NoClusterMgr(ClusterMgrBase):
    def __init__(self, bootstrap_address: str, service_manage_port: int=8080):
        super().__init__(bootstrap_address, cluster_mode=False, service_manage_port=service_manage_port)
            
    def refresh_service_nodes(self, service_name: str="infinistore"):
        # For NoCluster cluster, the service node address is 
        if len(self.service_nodes) > 0:
            return
        cluster_node_ip = self.cluster_nodes[0]
        service_host, service_port = cluster_node_ip.split(":")
        # Call service to get service running arguments        
        service_config = self.get_service_config(service_host=service_host, service_manage_port=self.service_manage_port)
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
        service_port = service_config['service_port']
        service_key = f"{service_host}:{service_port}"
        service_node = ServiceNode(
                host=service_host,
                port=service_port,
                manage_port=service_config['manage_port'],
                conn= infinistore.InfinityConnection(config)
            )
        self.service_nodes[service_key] = service_node
