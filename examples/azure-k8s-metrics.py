"""
This example demonstrates how to access Azure AKS cluster resource usage
which includes metrics like cpu/memory usage of nodes and pods.

To reterive kubeconfig file from azure 
az aks get-credentials --resource-group <RG> --name <K8s-cluster-name> --file <filename>

"""

from __future__ import print_function
import datetime
import os
from kubernetes import client, config
from kubernetes.client.api_client import ApiClient
from pprint import pprint
import json
import base64

class az_k8s_client:
    k8s_config = {}
    api_client=None
    aApiClient = None
    v1CoreAPI = None
    nodes = []
    namespaces = []
    pods = []
    cluster_report = {}
    pods_mem_usage = {}

    def __init__(self, k8s_name=None):
        if k8s_name != None:
            config_filepath = os.environ.get('HOME') + "/.kube/" + k8s_name
            config.load_kube_config(config_filepath)
            self.load_config(config_filepath)
            aConfiguration = client.Configuration()

            # Specify the endpoint of your Kube cluster
            aConfiguration.host = self.k8s_config["host"]
            aConfiguration.debug = False
            aConfiguration.verify_ssl = True
            aConfiguration.cert_file = "certs/cert.crt"
            aConfiguration.ssl_ca_cert = "certs/ca.crt"
            aConfiguration.key_file = "certs/key.pem"
            self.aApiClient = client.ApiClient(aConfiguration)

        self.v1CoreAPI = client.CoreV1Api()
        self.api_client = ApiClient()

    def load_config (self, k8s_name):
        fs = open(k8s_name, "r")
        os.system('mkdir -p certs')
        lines = fs.readlines()
        fs.close()
        for line in lines:
            if line.find("certificate-authority-data") != -1:
                ca =  line.split("certificate-authority-data:")[1]
                self.k8s_config["ca"] = str(base64.b64decode(ca), "utf-8")
                fsout = open("certs/ca.crt", "w")
                fsout.write(self.k8s_config["ca"])
                fsout.close()
            if line.find("server") != -1:
                self.k8s_config["host"] = str(line.split("server:")[1]).replace(' ', '').replace('\n', '')
            if line.find("client-certificate-data") != -1:
                self.k8s_config["cert"] = str(base64.b64decode(str(line.split("client-certificate-data:")[1])), "utf-8") 
                fsout = open("certs/cert.crt", "w")
                fsout.write(self.k8s_config["cert"])
                fsout.close()
            if line.find("client-key-data") != -1:
                self.k8s_config["key"] = str(base64.b64decode(str(line.split("client-key-data:")[1])), "utf-8") 
                fsout = open("certs/key.pem", "w")
                fsout.write(self.k8s_config["key"])
                fsout.close()
            if line.find("token") != -1:
                self.k8s_config["token"] = str(line.split("token:")[1])
            
    def list_namespaces (self):
        ret = self.v1CoreAPI.list_namespace(watch=False)
        for i in ret.items:            
            self.namespaces.append(i.metadata.name)         
        self.cluster_report["ns"] = self.namespaces

    def pod_resource_usage (self):
        if self.aApiClient == None:
            return
        req_url = self.k8s_config["host"] + '/apis/metrics.k8s.io/v1beta1/pods/'
        resp = self.aApiClient.request('GET', req_url)
        pods_metrics = json.loads(resp.data)
        for i in pods_metrics["items"]:
            ns_pod_key = i["metadata"]["namespace"] + ":" + i["metadata"]["name"]
            self.pods_mem_usage[ns_pod_key] = i["containers"][0]["usage"]

    def all_ns_list_pods (self):
        ret = self.v1CoreAPI.list_pod_for_all_namespaces(watch=False)
        for i in ret.items:            
            pod_info = {}
            pod_info["pod_name"] = i.metadata.name
            pod_info["namespace"] = i.metadata.namespace
            pod_info["ip"] = i.status.pod_ip

            pod_info["start_time"] = str(i.status.start_time.replace(tzinfo=None))
            delta = datetime.datetime.utcnow() - i.status.start_time.replace(tzinfo=None) 
            pod_info["age"] = str(delta.days) + " days " + str((delta.seconds  // (60 * 60))) + "h"
            pod_info["ready"]    = False
            if (i.status.container_statuses != None):
                pod_info["image"]    = i.status.container_statuses[0].image
                pod_info["image_id"] = i.status.container_statuses[0].image_id
                pod_info["name"]     = i.status.container_statuses[0].name
                pod_info["ready"]    = i.status.container_statuses[0].ready
                ns_pod_key = i.metadata.namespace + ":" + i.metadata.name
                pod_info["usage"]   = None
                if i.status.container_statuses[0].ready == True:
                    try:
                        pod_info["usage"] = self.pods_mem_usage[ns_pod_key]
                    except KeyError:
                        pass
            else:
                pod_info["message"] = i.status.message
                pod_info["reason"]  = i.status.reason
                pod_info["usage"]   = None
            self.pods.append(pod_info)
        self.cluster_report["pods"] = self.pods

    def list_node (self):
        ret = self.v1CoreAPI.list_node()       
        for i in ret.items:
            node_info = {}
            node_info["name"] = i.metadata.labels["kubernetes.io/hostname"]
            node_info["agentpool"] = i.metadata.labels["agentpool"]
            
            node_info["instancetype"] = i.metadata.labels['beta.kubernetes.io/instance-type']
            node_info["cpu"] = i.status.capacity["cpu"]
            node_info["sys_memory"] = i.status.capacity["memory"]
            node_info["os_image"] = i.status.node_info.os_image
            node_info["architecture"] = i.status.node_info.architecture
            node_info["kubelet_version"] = i.status.node_info.kubelet_version
            node_info["start_time"] = str(i.metadata.creation_timestamp)
            delta = datetime.datetime.utcnow() - i.metadata.creation_timestamp.replace(tzinfo=None)
            node_info["age"] = str(delta.days) + " days " + str((delta.seconds  // (60 * 60))) + "h"
            memory_usage = self.node_resource_usage(node_info["name"])
            node_info["memory_usage"] = memory_usage
            self.nodes.append(node_info)
        self.cluster_report["nodes"] = self.nodes

    def node_resource_usage (self, nodeName=None):
        if self.aApiClient == None:
            return
        req_url = self.k8s_config["host"] + '/apis/metrics.k8s.io/v1beta1/nodes/'+nodeName
        resp = self.aApiClient.request('GET', req_url)
        nodes_metrics = json.loads(resp.data)
        memory_usage = float(str(nodes_metrics["usage"]["memory"]).split("Ki")[0]) / (1024.0 * 1024.0) 
        return memory_usage

    def nodes_resource_usage (self, nodeName=None):
        if self.aApiClient == None:
            return        
        if nodeName == None:
            req_url = self.k8s_config["host"] + '/apis/metrics.k8s.io/v1beta1/nodes/'
            resp = self.aApiClient.request('GET', req_url)
            nodes_metrics = json.loads(resp.data)
            for i in nodes_metrics["items"]:
                memory_usage = float(str(i["usage"]["memory"]).split("Ki")[0]) / (1024.0 * 1024.0)
        else:
            req_url = self.k8s_config["host"] + '/apis/metrics.k8s.io/v1beta1/nodes/'+nodeName
            resp = self.aApiClient.request('GET', req_url)
            nodes_metrics = json.loads(resp.data)
            memory_usage = float(str(nodes_metrics["usage"]["memory"]).split("Ki")[0]) / (1024.0 * 1024.0)     
        return memory_usage

    def display_cluster_metrics (self):
        for node in self.cluster_report["nodes"]:
            print("%s\t%s\t%s\t%s\t%.2f Gb\t%.2f Gb" % (node["name"], node["cpu"], 
            node["instancetype"], node["kubelet_version"], 
            float(node["sys_memory"].split("Ki")[0]) / (1024.0 * 1024.0),
            node["memory_usage"]))

        for namespace in self.cluster_report["ns"]:
            print("%s" % (namespace))
        mem_usage = 0
        for pod in self.cluster_report["pods"]:
            if pod["usage"] != None and pod["usage"]["memory"].find("Ki") != -1:
                mem_usage = int(pod["usage"]["memory"].split("Ki")[0]) / 1024
            elif pod["usage"] != None and pod["usage"]["memory"].find("Mi") != -1:
                mem_usage = int(pod["usage"]["memory"].split("Mi")[0]) / 1024

            print("%s\t%s\t%s\t%d Mb" % (pod["namespace"], pod["pod_name"], pod["age"], mem_usage))

    def write_md_report (self):
        output_file = open("usage-report.md", "w", encoding="utf-8")
        
        # output_file.write("# Cluster: %s\n\n" % self.k8s_config["name"])
        output_file.write("## VM Nodes usage\n")
        output_file.write("| Name | CoreCount | InstanceType | K8s version | Memory GB | Memory Usage Gb |  Usage% |\n")
        output_file.write("| :-------- | :------- | :--- | :--- | :--- |:--- | :----|\n")
        for node in self.cluster_report["nodes"]:
            sys_memory = float(node["sys_memory"].split("Ki")[0]) / (1024.0 * 1024.0)
            output_file.write("|%s |%s| %s | %s | %.2f Gb	| %.2f Gb | %d %%|\n" 
            % (node["name"], node["cpu"], node["instancetype"], node["kubelet_version"], 
            sys_memory, node["memory_usage"], int((node["memory_usage"] / sys_memory) * 100)))

        output_file.write("\n")
        output_file.write("## Namespace/Pods usage\n")
        output_file.write("|Namespace|POD Name| Age | Memory Usage |\n")
        output_file.write("| :--| :-- | :-- | :-- |\n")
        for pod in self.cluster_report["pods"]:
            if pod["usage"] != None and pod["usage"]["memory"].find("Ki") != -1:
                mem_usage = int(pod["usage"]["memory"].split("Ki")[0]) / 1024
            elif pod["usage"] != None and pod["usage"]["memory"].find("Mi") != -1:
                mem_usage = int(pod["usage"]["memory"].split("Mi")[0]) / 1024
                
            output_file.write("|%s|%s|%s|%d Mb|\n" % (pod["namespace"], pod["pod_name"], pod["age"], mem_usage))
        
        output_file.write("\n---\n\n")
        output_file.write("## Feedback\n")
        output_file.write("If you have any feedback, please reach out here")
        output_file.close()

def main ():
    k8s_cluster = az_k8s_client("aks-demo-k8s.conf")

    # construct all k8s resource and its usage
    k8s_cluster.pod_resource_usage()
    k8s_cluster.list_node()
    k8s_cluster.list_namespaces()
    k8s_cluster.all_ns_list_pods()

    # display usage report and also write .md file
    k8s_cluster.display_cluster_metrics()
    k8s_cluster.write_md_report()

if __name__ == '__main__':
    main()
