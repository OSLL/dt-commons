#!/usr/bin/env python3
#This script is part of the DT Architecture Library for dt-commons

import yaml
import docker
import os
import git
import glob

from git import Repo
from .arch_message import ApiMessage
from .arch_worker import ApiWorker

'''
    THIS LIB INCLUDES FUNCTIONS THAT ALLOW TO COMMUNICATE WITH AN ARCHITECTURE
    API RUNNING ON A SINGLE ROBOT (MSG TYPES FOR VARIOUS ENDPOINTS OF A SINGLE
    ARCHITECTURE API), BUT DO NOT SPECIFY THE REQUIRED API FOR THAT. I.E. THE
    REQUIRED SERVER IS NOT RUNNING WITHIN THE LIBRARY
'''

class ArchAPIClient:
    def __init__(self, hostname="hostname", robot_type=None, client=None):
        #Initialize robot hostname & docker.DockerClient()
        self.hostname = hostname
        self.client = client

        #Initialize folders and directories
        self.active_config = None
        self.config_path = None
        self.module_path = None
        self.current_configuration = "none"

        self.dt_version = "ente"
        self.status = ApiMessage()
        self.error = ApiMessage()
        self.work = ApiWorker(self.client)

        #Retract robot_type
        if robot_type is None:
            if os.path.isfile("/data/config/robot_type"):
                self.robot_type = open("/data/config/robot_type").readline()
            elif os.path.isfile("/data/stats/init_sd_card/parameters/robot_type"):
                self.robot_type = open("/data/stats/init_sd_card/parameters/robot_type").readline()
            else: #error upon initialization = status
                self.status("error", "Could not find robot type from expected paths", None).msg
        else:
            self.robot_type = robot_type

        #Include ente version of dt-architecture-data repo
        if not os.path.isdir("/data/assets/dt-architecture-data"):
            os.makedirs("/data/assets", exist_ok=True)
            git.Git("/data/assets").clone("git://github.com/duckietown/dt-architecture-data.git", branch=self.dt_version)

        self.config_path = "/data/assets/dt-architecture-data/configurations/"+self.robot_type
        self.module_path = "/data/assets/dt-architecture-data/modules/"

        #Initialize configuration & module endpoints
        self.configuration = []  #empty array, with all endpoints in it
        self.module = []  #empty list, with all endpoints in it


#RE-USE INITIALIZED PATHS: in multi_arch_client
    def config_path(self):
        return self.config_path

    def module_path(self):
        return self.module_path


#PASSIVE MESSAGING: monitoring (info, list, status) requests
    def default_response(self):
        return self.status.msg

    #def configuration_status(self):
    #    self.configuration_status = json.dumps(self.status)
    #    return self.configuration_status

    def configuration_list(self):
        configuration_list = {} #re-initialize every time called for (empty when error)
        if self.config_path is not None:
            config_paths = glob.glob(self.config_path + "/*.yaml")
            configuration_list["configurations"] = [os.path.splitext(os.path.basename(f))[0] for f in config_paths]
        else: #error msg
            return self.error("error", "could not find configurations (dt-docker-data)", None).msg
        return configuration_list


    def configuration_info(self, config):
        try:
            with open(self.config_path + "/" + config + ".yaml", 'r') as file:
                configuration_info = yaml.load(file, Loader=yaml.FullLoader)
                if "modules" in configuration_info:
                    mods = configuration_info["modules"]
                    for m in mods:
                        if "type" in mods[m]:
                            mod_type = mods[m]["type"]
                            mod_config = self.module_info(mod_type)
                            if "configuration" in mod_config:
                                #Virtually append module configuration info to configuration file
                                configuration_info["modules"][m]["configuration"] = mod_config["configuration"]

                return configuration_info

        except FileNotFoundError: #error msg
            return self.error("error", "Configuration file not found", self.config_path + "/" + config + ".yaml").msg


    def module_list(self):
        module_list = {} #re-initialize every time called for (empty when error)
        yaml_paths = glob.glob(self.module_path + "/*.yaml")
        for file in yaml_paths:
            try:
                with open(file, 'r') as fd:
                    print ("loading module: " + file)
                    config = yaml.load(fd, Loader=yaml.FullLoader)
                    filename, ext = os.path.splitext(os.path.basename(file))
                    module_list["modules"] = [] #put here, so error msg can be sent
                    module_list["modules"].append(filename)
            except FileNotFoundError: #error msg
                return self.error("error", "Module file not found", self.module_path + "/" + file + ".yaml").msg
        return module_list


    def module_info(self, module):
        try:
            with open(self.module_path + "/" + module + ".yaml", 'r') as fd:
                module_info = yaml.load(fd, Loader=yaml.FullLoader)
                config = module_info["configuration"]

                #Update ports for pydocker from docker-compose
                if "ports" in config:
                    ports = config["ports"]
                    newports = {}
                    for p in ports:
                        external,internal = p.split(":", 1)
                        newports[internal]=int(external)
                    config["ports"] = newports
                #Update volumes for pydocker from docker-compose
                if "volumes" in config:
                    vols = config["volumes"]
                    newvols = {}
                    for v in vols:
                        host, container = v.split(":", 1)
                        newvols[host] = {'bind': container, 'mode':'rw'} #what happens here?
                    config["volumes"] = newvols
                #Update restart_policy
                if "restart" in config:
                    config.pop("restart")
                    restart_policy = {"Name":"always"}
                #Update container_name
                if "container_name" in config:
                    config["name"] = config.pop("container_name")
                #Update image
                if "image" in config:
                    config["image"] = config["image"].replace('${ARCH-arm32v7}','arm32v7' )

                return module_info

        except FileNotFoundError: #error msg
            return self.error("error", "Module not found", self.module_path + module + ".yaml").msg


#ACTIVE MESSAGING: activation (pull, stop, ...) requests requiring a DockerClient()
    def configuration_set_config(self, config):
        #Get virtually extended config file with module specs
        mod_config = self.configuration_info(config)
        return self.work.set_config(mod_config)


    def pull_image(self, url):
        #url of form {image_url}:{image_tag}
        return self.work.pull_image(url)


    def monitor_id(self, id):
        #Get current job status, using id=ETag
        if int(id) in self.work.log:
            return self.work.log[int(id)]
        else:
            return self.work.log.copy()


    def clear_job_log(self):
        return self.work.clear_log()
