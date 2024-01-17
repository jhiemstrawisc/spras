import os
import platform
import re
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple, Union

import docker

import spras.config as config
from spras.util import hash_filename

import subprocess
from datetime import datetime 

def prepare_path_docker(orig_path: PurePath) -> str:
    """
    Prepare an absolute path for mounting as a Docker volume.
    Converts Windows file separators to posix separators.
    Converts Windows drive letters in absolute paths.
    """
    # TODO consider testing PurePath.is_absolute()
    prepared_path = orig_path.as_posix()
    # Check whether the path matches an absolute Windows path with a drive letter
    match = re.match(r'^([A-Z]:)(.*)', prepared_path)
    if match:
        # The first group is the drive such as C:
        drive = match.group(1).lower()[0]
        # The second group is the rest of the path such as /Users/me
        prepared_path = match.group(2)
        prepared_path = '//' + drive + prepared_path
    return prepared_path


def convert_docker_path(src_path: PurePath, dest_path: PurePath, file_path: Union[str, PurePath]) -> PurePosixPath:
    """
    Convert a file_path that is in src_path to be in dest_path instead.
    For example, convert /usr/mydir and /usr/mydir/myfile and /tmp to /tmp/myfile
    @param src_path: source path that is a parent of file_path
    @param dest_path: destination path
    @param file_path: filename that is under the source path
    @return: a new path with the filename relative to the destination path
    """
    rel_path = file_path.relative_to(src_path)
    return PurePosixPath(dest_path, rel_path)

def download_gcs(gcs_path: str, local_path: str, is_dir: bool):
    # check that output path exists
    if not os.path.exists(Path(local_path).parent):
        os.makedirs(Path(local_path).parent)

    # build command
    cmd = 'gcloud storage'
    cmd = cmd + ' cp'
    if is_dir:
        cmd = cmd + ' -r'
    cmd = cmd + ' ' + gcs_path + '/* ' + local_path

    print(cmd)
    # run command 
    subprocess.run(cmd, shell=True)

def upload_gcs(local_path: str, gcs_path: str, is_dir: bool):
    # build command
    cmd = 'gcloud storage'
    cmd = cmd + ' cp'
    if is_dir:
        cmd = cmd + ' -r'
    cmd = cmd + ' ' + str(Path(local_path).resolve()) + ' ' + gcs_path

    print(cmd)
    # run command
    subprocess.run(cmd, shell=True)
    
def prepare_dsub_cmd(flags: dict):
    # set constant flags
    dsub_command = 'dsub'
    flags['provider'] = 'google-cls-v2'
    flags['regions'] = 'us-central1'
    flags['user-project'] = os.getenv('GOOGLE_PROJECT')
    flags['project'] = os.getenv('GOOGLE_PROJECT')
    flags['network'] = 'network'
    flags['subnetwork'] = 'subnetwork'
    flags['service-account'] = subprocess.run(['gcloud', 'config' ,'get-value' ,'account'], capture_output=True, text=True).stdout.replace('\n', '')

    # order flags according to flag_list
    flag_list = ["provider", "regions", "zones", "location", "user-project", "project", "network", "subnetwork", "service-account", "image", "env", "logging", "input", "input-recursive", "mount", "output", "output-recursive", "command", "script"]
    ordered_flags = {f:flags[f] for f in flag_list if f in flags.keys()}

    # iteratively add flags to the command 
    for flag in ordered_flags.keys():
        if isinstance(ordered_flags.get(flag), list):
            for f in ordered_flags.get(flag):
                dsub_command = dsub_command + " --" + flag + " " + f
        else:
            dsub_command = dsub_command + " --" + flag + " " + ordered_flags.get(flag)

    # Wait for dsub job to complegte
    dsub_command = dsub_command + " --wait"
    print(f"Command: {dsub_command}")
    return dsub_command


# TODO consider a better default environment variable
# TODO environment currently a single string (e.g. 'TMPDIR=/OmicsIntegrator1'), should it be a list?
# run_container_singularity assumes a single string
# Follow docker-py's naming conventions (https://docker-py.readthedocs.io/en/stable/containers.html)
# Technically the argument is an image, not a container, but we use container here.
def run_container(framework: str, container_suffix: str, command: List[str], volumes: List[Tuple[PurePath, PurePath]], working_dir: str, environment: str = 'SPRAS=True'):
    """
    Runs a command in the container using Singularity or Docker
    @param framework: singularity or docker
    @param container_suffix: name of the DockerHub container without the 'docker://' prefix
    @param command: command to run in the container
    @param volumes: a list of volumes to mount where each item is a (source, destination) tuple
    @param working_dir: the working directory in the container
    @param environment: environment variables to set in the container
    @return: output from Singularity execute or Docker run
    """
    normalized_framework = framework.casefold()

    container = config.config.container_prefix + "/" + container_suffix
    if normalized_framework == 'docker':
        return run_container_docker(container, command, volumes, working_dir, environment)
    elif normalized_framework == 'singularity':
        return run_container_singularity(container, command, volumes, working_dir, environment)
    elif normalized_framework == 'dsub':
        return run_container_dsub(container, command, volumes, working_dir, environment)
    else:
        raise ValueError(f'{framework} is not a recognized container framework. Choose "docker" or "singularity".')


# TODO any issue with creating a new client each time inside this function?
def run_container_docker(container: str, command: List[str], volumes: List[Tuple[PurePath, PurePath]], working_dir: str, environment: str = 'SPRAS=True'):
    """
    Runs a command in the container using Docker.
    Attempts to automatically correct file owner and group for new files created by the container, setting them to the
    current owner and group IDs.
    Does not modify the owner or group for existing files modified by the container.
    @param container: name of the DockerHub container without the 'docker://' prefix
    @param command: command to run in the container
    @param volumes: a list of volumes to mount where each item is a (source, destination) tuple
    @param working_dir: the working directory in the container
    @param environment: environment variables to set in the container
    @return: output from Docker run
    """
    out = None
    try:
        # Initialize a Docker client using environment variables
        client = docker.from_env()
        # Track the contents of the local directories that will be bound so that new files added can have their owner
        # changed
        pre_volume_contents = {}
        src_dest_map = {}
        for src, dest in volumes:
            src_path = Path(src)
            # The same source path can be in volumes more than once if there were multiple input or output files
            # in the same directory
            # Only check each unique source path once and track which of the possible destination paths was used
            if src_path not in pre_volume_contents:
                # Only list files in the directory, do not walk recursively because it could include
                # a massive number of files
                pre_volume_contents[src_path] = set(src_path.iterdir())
                src_dest_map[src_path] = dest

        bind_paths = [f'{prepare_path_docker(src)}:{dest}' for src, dest in volumes]

        out = client.containers.run(container,
                                    command,
                                    stderr=True,
                                    volumes=bind_paths,
                                    working_dir=working_dir,
                                    environment=[environment]).decode('utf-8')

        # TODO does this cleanup need to still run even if there was an error in the above run command?
        # On Unix, files written by the above Docker run command will be owned by root and cannot be modified
        # outside the container by a non-root user
        # Reset the file owner and the group inside the container
        try:
            # Only available on Unix
            uid = os.getuid()
            gid = os.getgid()

            all_modified_volume_contents = set()
            for src_path in pre_volume_contents.keys():
                # Assumes the Docker run call is the only process that modified the contents
                # Only considers files that were added, not files that were modified
                post_volume_contents = set(src_path.iterdir())
                modified_volume_contents = post_volume_contents - pre_volume_contents[src_path]
                modified_volume_contents = [str(convert_docker_path(src_path, src_dest_map[src_path], p)) for p in
                                            modified_volume_contents]
                all_modified_volume_contents.update(modified_volume_contents)

            # This command changes the ownership of output files so we don't
            # get a permissions error when snakemake or the user try to touch the files
            # Use --recursive because new directories could have been created inside the container
            # Do not run the command if no files were modified
            if len(all_modified_volume_contents) > 0:
                chown_command = ['chown', f'{uid}:{gid}', '--recursive']
                chown_command.extend(all_modified_volume_contents)
                chown_command = ' '.join(chown_command)
                client.containers.run(container,
                                    chown_command,
                                    stderr=True,
                                    volumes=bind_paths,
                                    working_dir=working_dir,
                                    environment=[environment]).decode('utf-8')

        # Raised on non-Unix systems
        except AttributeError:
            pass

        # TODO: Not sure whether this is needed or where to close the client
        client.close()

    except Exception as err:
        print(err)
    # Removed the finally block to address bugbear B012
    # "`return` inside `finally` blocks cause exceptions to be silenced"
    # finally:
    return out


def run_container_singularity(container: str, command: List[str], volumes: List[Tuple[PurePath, PurePath]], working_dir: str, environment: str = 'SPRAS=True'):
    """
    Runs a command in the container using Singularity.
    Only available on Linux.
    @param container: name of the DockerHub container without the 'docker://' prefix
    @param command: command to run in the container
    @param volumes: a list of volumes to mount where each item is a (source, destination) tuple
    @param working_dir: the working directory in the container
    @param environment: environment variable to set in the container
    @return: output from Singularity execute
    """
    # spython is not compatible with Windows
    if platform.system() != 'Linux':
        raise NotImplementedError('Singularity support is only available on Linux')

    # See https://stackoverflow.com/questions/3095071/in-python-what-happens-when-you-import-inside-of-a-function
    from spython.main import Client

    bind_paths = [f'{prepare_path_docker(src)}:{dest}' for src, dest in volumes]

    # TODO is try/finally needed for Singularity?
    singularity_options = ['--cleanenv', '--containall', '--pwd', working_dir]
    # Singularity does not allow $HOME to be set as a regular environment variable
    # Capture it and use the special argument instead
    if environment.startswith('HOME='):
        home_dir = environment[5:]
        singularity_options.extend(['--home', home_dir])
    else:
        singularity_options.extend(['--env', environment])

    # To debug a container add the execute arguments: singularity_options=['--debug'], quiet=False
    # Adding 'docker://' to the container indicates this is a Docker image Singularity must convert
    return Client.execute('docker://' + container,
                          command,
                          options=singularity_options,
                          bind=bind_paths)

# Because this is called independently for each file, the same local path can be mounted to multiple volumes
def prepare_volume(filename: Union[str, PurePath], volume_base: Union[str, PurePath]) -> Tuple[Tuple[PurePath, PurePath], str]:
    """
    Makes a file on the local file system accessible within a container by mapping the local (source) path to a new
    container (destination) path and renaming the file to be relative to the destination path.
    The destination path will be a new path relative to the volume_base that includes a hash identifier derived from the
    original filename.
    An example mapped filename looks like '/spras/MG4YPNK/oi1-edges.txt'.
    @param filename: The file on the local file system to map
    @param volume_base: The base directory in the container, which must be an absolute directory
    @return: first returned object is a tuple (source path, destination path) and the second returned object is the
    updated filename relative to the destination path
    """
    base_path = PurePosixPath(volume_base)
    if not base_path.is_absolute():
        raise ValueError(f'Volume base must be an absolute path: {volume_base}')

    if isinstance(filename, PurePath):
        filename = str(filename)

    filename_hash = hash_filename(filename, config.config.hash_length)
    dest = PurePosixPath(base_path, filename_hash)

    abs_filename = Path(filename).resolve()
    container_filename = str(PurePosixPath(dest, abs_filename.name))
    if abs_filename.is_dir():
        dest = PurePosixPath(dest, abs_filename.name)
        src = abs_filename
    else:
        parent = abs_filename.parent
        if parent.as_posix() == '.':
            parent = Path.cwd()
        src = parent

    return (src, dest), container_filename

def run_container_dsub(container: str, command: List[str], volumes: List[Tuple[PurePath, PurePath]], working_dir: str, environment: str = 'SPRAS=True'):
    """
    Runs a command in the container using Docker.
    Attempts to automatically correct file owner and group for new files created by the container, setting them to the
    current owner and group IDs.
    Does not modify the owner or group for existing files modified by the container.
    @param container: name of the container in the Google Cloud Container Registry 
    @param command: command to run in the container
    @param volumes: a list of volumes to mount where each item is a (source, destination) tuple
    @param working_dir: the working directory in the container
    @param environment: environment variables to set in the container
    @return: path of output from dsub 
    """
    # Dictionary of flags for dsub command
    flags = dict()

    workspace_bucket = os.getenv('WORKSPACE_BUCKET')
    # Add path in the workspace bucket and label for dsub command for each volume
    dsub_volumes = [(src, dst, workspace_bucket +  str(dst), "INPUT_" + str(i),) for i, (src, dst) in enumerate(volumes)]
    
    # Prepare command that will be run inside the container for dsub 
    container_command = list()
    for item in command:
        # Replace each volume with path in workspace 
        to_replace = ["${"+path[3]+'}' for path in dsub_volumes if str(path[1]) in item]
        if len(to_replace) == 1 and len(PurePath(item).suffix) > 0:
            container_command.append(to_replace[0]+'/'+item.split('/')[-1])
        elif len(to_replace) == 1 and len(PurePath(item).suffix) == 0:
            container_command.append(to_replace[0]+'/')
        else:
            container_command.append(item)
    # Add a command to copy the volumes to the workspace buckets
    container_command.append(('; cp -rf ' + f'/mnt/data/input/gs/{workspace_bucket}{working_dir}/*' + ' $OUTPUT').replace('gs://', ''))

    # Make the command into a string
    flags['command'] = ' '.join(container_command)
    flags['command'] = "'" + flags['command'] + "'"
    
    ## Push volumes to WORKSPACE_BUCKET
    for src, dst, gcs_path, env in dsub_volumes:
        upload_gcs(local_path=str(src), gcs_path=gcs_path, is_dir=True)
    
    ## Prepare flags for dsub command
    flags['image'] = container
    flags['env'] = environment
    flags['input-recursive'] = [vol[3]+'='+vol[2] for vol in dsub_volumes]
    flags['output-recursive'] = "OUTPUT=" + workspace_bucket +  working_dir
    flags['logging'] = workspace_bucket + '/dsub/'
    
    # Create dsub command 
    dsub_command = prepare_dsub_cmd(flags)
    
    # Run dsub as subprocess
    subprocess.run(dsub_command, shell=True)
    
    # Pull output volumes from WORKSPACE_BUCKET
    for src, dst, gcs_path, env in dsub_volumes:
        download_gcs(local_path=str(src), gcs_path=gcs_path, is_dir=True)  
    
    # return location of dsub logs in WORKSPACE_BUCKET
    return  'dsub logs: {logs}'.format(logs = flags['logging'])