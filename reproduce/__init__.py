#!/usr/bin/python2
import os
import argparse
import subprocess
import git
import fnmatch
import sys
from shutil import copyfile
import logging
from colorlog import ColoredFormatter

this_path = os.path.abspath(os.getcwd())

root_repo_dir_name = "repositories"
root_artifacts_dir_name = "artifacts"
config_name = "config.py"

root_repository_dir = os.path.join(this_path, root_repo_dir_name)
root_artifacts_dir = os.path.join(this_path, root_artifacts_dir_name)

demo_config_list = [] #list of config.py paths
options = None
reserved_directories = ["toolchains", "artifacts", "repositories"]
info_types = {"info":"white", "warning":"yellow", "error":"red", "success":"green", "finish":"green"}
toolchain_map = {"arm-none-eabi":"/opt/gcc-arm-none-eabi/bin", "zephyr-sdk":"/opt/zephyr-sdk", "riscv-unknown-elf-gcc":"/opt/riscv-unknown-elf-gcc/bin"}

error_list = []

class Config:

    config_path = ""
    config_dir_path = ""
    build_path = ""
    repository_name = ""
    git_url = ""
    commit_sha = ""
    patches = []
    env_settings = []
    toolchain_url = ""
    samples = []
    prebuild_commands = []

    def __init__(self, config_path, repository_name, git_url, commit_sha, patches, env_settings, toolchain, samples, prebuild_commands):
        #all configs must be provided even if empty
        self.config_path = config_path #path to config.py
        self.config_dir_path = config_path.rsplit(os.sep, 1)[0] #path to the directory with config.py
        self.repository_name = repository_name #directory name to which the repository will be cloned
        self.git_url = git_url #URL of the git respository
        self.commit_sha = commit_sha #commit SHA
        self.patches = patches #list of patches to apply
        self.env_settings = env_settings #environment variables settings
        self.toolchain = toolchain #name of the toolchain to be used
        self.samples = samples #list of dictionaries which gives info about directory where the sample lies, what are the build commands and what are the names of artifacts.
        self.prebuild_commands = prebuild_commands #list of commands to run before build commands

def error(msg):
    log.error(msg)
    error_list.append(msg)

def exit_status():
    print("--------------------------------------------------------------------------")
    if error_list:
        for er in error_list:
            log.error(er)
        print("--------------------------------------------------------------------------")
        return 1
    else:
        log.info('Build succeeded for all samples!')
        print("--------------------------------------------------------------------------")
        return 0

def prepare_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbosity. Use with GIT_PYTHON_TRACE=full for git debugging")
    parser.add_argument("-p", "--path", dest="demo_config_path", help="Set path to demo config file")
    return parser

def search_configs():
    log.debug('Looking for configs...')
    demo_config_path = options.demo_config_path
    if demo_config_path is not None:
        if os.path.isfile(demo_config_path):
            demo_config_list.append(os.path.join(this_path, demo_config_path))
        else:
            error('Config file was not found in provided path: '+demo_config_path)
    else:
        for root, dirs, files in os.walk(this_path):
            for d in reserved_directories:
                if d in dirs:
                    dirs.remove(d)
            for name in files:
                if fnmatch.fnmatch(name, config_name):
                    log.info('Found config in: '+os.path.join(root, name))
                    demo_config_list.append(os.path.join(root, name))
                    break

def run_prebuild_commands(cfg):
    path = os.path.join(root_repository_dir, cfg.repository_name)
    os.chdir(path)
    if not cfg.prebuild_commands:
        return False
    for command in cfg.prebuild_commands:
        try:
            status = subprocess.call(command, shell=True)
            if status != 0:
                error("Prebuild command failed with status {0}.".format(status))
                return True
        except OSError, e:
            error("Failed to run command '{0}' : {1}".format(command, str(e)))
            return True
        return False

def prepare_toolchain(cfg):
    if cfg.toolchain == None:
        log.debug('Skipping toolchain configuration.')
        return False
    if toolchain_map.has_key(cfg.toolchain):
        path_to_add = toolchain_map[cfg.toolchain]
        if not os.path.exists(path_to_add):
            error('Toolchain: '+cfg.toolchain+' was not found in: '+path_to_add+'.')
            return True
        log.debug('Adding toolchain: '+path_to_add+' to PATH.')
        if not (path_to_add in os.environ['PATH'].split(os.pathsep)): #check if the toolchain is already in the PATH
            os.environ['PATH'] += os.pathsep + path_to_add
    else:
        error('Toolchain: '+cfg.toolchain+' not available'+'. List of available toolchains: '+str(toolchain_map.keys()))
        return True
    log.info('Toolchain: '+cfg.toolchain+' configured.')
    return False

def prepare_repository(cfg):
    path = os.path.join(root_repository_dir, cfg.repository_name)
    if cfg.repository_name == "":
        error("Empty repository_name in: "+cfg.config_path)
        return True
    if not os.path.exists(path):
        log.debug('Creating '+cfg.repository_name+'...')
        os.makedirs(path) #mkdir for the repository
        log.debug('Cloning '+cfg.repository_name+' URL: '+cfg.git_url+' to '+path+'...')
        git.Repo.clone_from(cfg.git_url, path) #git clone
        repo = git.Repo(path) #get repository path
    else:
        log.warning('Repository: '+path+' already exists!')
        repo = git.Repo(path) #get repository path
        if (repo.remotes.origin.url != cfg.git_url):
            error('URLs not matching for: '+path+' repository. Expected: '+repo.remotes.origin.url+', got: '+cfg.git_url)
            return True
        else:
            log.debug('Fetching remotes...')
            remote_commit = repo.remotes[0].fetch()

    #checkout to given SHA
    if cfg.commit_sha != "":
        log.debug('Checking out in repository: '+cfg.repository_name+' to SHA: '+cfg.commit_sha)
        repo.git.reset("--hard", cfg.commit_sha) #reset target repository to given SHA
        repo.git.submodule("foreach", "--recursive", "git", "reset", "--hard") #clean the submodules from leftovers
        repo.git.submodule("foreach", "--recursive", "git", "clean", "-fxd")
        repo.git.submodule("update", "--init", "--recursive") #update submodules
        repo.git.clean("-fxd") #clean target repository from untracked files and directories
    else:
        error("No SHA provided in: "+cfg.config_path)
        return True

    #apply patches
    if cfg.patches != None:
        if isinstance(cfg.patches, list):
            for patch in cfg.patches:
                log.debug('Applying patch: '+patch+' in repository: '+cfg.repository_name)
                if os.path.exists(os.path.join(cfg.config_dir_path, patch)):
                    repo.git.apply(os.path.join(cfg.config_dir_path, patch)) #apply patch
                else:
                    error("No patch: "+patch+" in: "+cfg.config_dir_path)
                    return True
        else:
            error('Config patches:'+str(cfg.patches)+' in: '+cfg.config_path+' is not a list.')
            return True

    log.info('Repository configured for demo: '+cfg.config_dir_path)
    return False

def prepare_environment(cfg):
    if cfg.env_settings:
        for setting in cfg.env_settings:
            if not isinstance(setting, tuple):
                error("Environment config: "+str(setting)+" in: "+cfg.config_path+" is not a tuple.")
                return True
            elif not (len(setting) == 2) and not(len(setting) == 1):
                error("Environment config: "+str(setting)+" in: "+cfg.config_path+" must have only one or two elements per tuple.")
                return True
            else:
                if len(setting) == 2:
                    os.environ[setting[0]] = setting[1] #set up the environment if needed
                else:
                    os.environ[setting[0]] = ""
    else:
        log.warning('No environment settings provided in: '+cfg.config_path)

    return False

def prepare_directories(cfg):
    path = os.path.join(root_artifacts_dir, os.path.relpath(cfg.config_dir_path))
    cfg.config_elf_path = path
    if not os.path.exists(path):
        os.makedirs(path)
    return False

def make_samples(cfg):
    for sample in cfg.samples:
        if isinstance(sample["directory"], str):
            path = os.path.join(root_repository_dir, cfg.repository_name, sample["directory"])
            os.chdir(path) #go to repository root
        else:
            error('Config sample["directory"]: '+str(sample["directory"])+' is not a string type.')
            return True

        if isinstance(sample["build_commands"], list):
            for cmd in sample["build_commands"]:
                if os.system(cmd):
                    error("Build command failed in: "+cfg.config_path+", command: "+cmd)
                    return True
        else:
            error('Config sample["build_commands"]: '+str(sample["build_commands"])+' is not a list type.')
            return True

        for art in sample["artifacts"]:
            if isinstance(art, dict):
                for art in sample["artifacts"]:
                    elf_path = os.path.join(path, art["from"])
                    if os.path.exists(elf_path):
                        copyfile(elf_path, os.path.join(cfg.config_elf_path, art["to"]))
            elif isinstance(art, str):
                elf_path = os.path.join(path, art)
                if os.path.exists(elf_path):
                    copyfile(elf_path, os.path.join(cfg.config_elf_path, art))
                else:
                    error("Binary: "+elf_path+" does not exists. Wrong name?")
                    return True
            else:
                error("Wrong artifacts type in: "+cfg.config_path+" Expected dictionary or list.")
                return True
        log.info('Build succeeded for: '+path)

    #go back to root
    os.chdir(this_path)
    return False

def build_demos():
    for item in demo_config_list:
        d = locals() #set up the dictionary to read out the config.py
        d["repository_name"]=None
        d["git_url"]=None
        d["commit_sha"]=None
        d["patches"]=None
        d["env_settings"]=None
        d["toolchain"]=None
        d["samples"]=None
        d["prebuild_commands"]=None
        execfile(item, d) #load variables from config.py
        conf_obj = Config(item, d["repository_name"], d["git_url"], d["commit_sha"], d["patches"], d["env_settings"], d["toolchain"], d["samples"], d["prebuild_commands"]) #initialize Config object for a target sample
        if prepare_toolchain(conf_obj):
            continue
        if prepare_repository(conf_obj):
            continue
        if prepare_environment(conf_obj):
            continue
        if prepare_directories(conf_obj):
            continue
        if run_prebuild_commands(conf_obj):
            continue
        if make_samples(conf_obj):
            os.chdir(this_path)
            continue

def configure_logger():
    global log
    logFormat = "  %(log_color)s%(levelname)-8s%(reset)s | %(log_color)s%(message)s%(reset)s"
    logging.root.setLevel(logging.INFO)
    formatter = ColoredFormatter(logFormat)
    stream = logging.StreamHandler()
    stream.setLevel(logging.DEBUG)
    stream.setFormatter(formatter)
    logging.root.addHandler(stream)
    log = logging.root

def main():
    global options
    parser = prepare_parser()
    options = parser.parse_args()
    configure_logger()
    search_configs()
    build_demos()
    status = exit_status()
    print('Script exited with status %d.' % status)
    sys.exit(status)

if __name__ == "__main__":
    main()
