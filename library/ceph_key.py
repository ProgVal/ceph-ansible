#!/usr/bin/python
# Copyright 2018, Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: ceph_key

author: Sebastien Han <seb@redhat.com>

short_description: Manage Cephx key(s)

version_added: "2.6"

description:
    - Manage CephX creation, deletion and updates.
    It can also list and get information about keyring(s).
options:
    cluster:
        description:
            - The ceph cluster name.
        required: false
        default: ceph
    name:
        description:
            - name of the CephX key
        required: true
    state:
        description:
            - If 'present' is used, the module creates a keyring
            with the associated capabilities.
            If 'present' is used and a secret is provided the module
            will always add the key. Which means it will update
            the keyring if the secret changes, the same goes for
            the capabilities.
            If 'absent' is used, the module will simply delete the keyring.
            If 'list' is used, the module will list all the keys and will
            return a json output.
            If 'update' is used, the module will **only** update
            the capabilities of a given keyring.
            If 'info' is used, the module will return in a json format the
            description of a given keyring.
        required: true
        choices: ['present', 'absent', 'list', 'update', 'info']
        default: list
    caps:
        description:
            - CephX key capabilities
        default: None
        required: false
    secret:
        description:
            - keyring's secret value
        required: false
        default: None
    containerized:
        description:
            - Wether or not this is a containerized cluster. The value is
            assigned or not depending on how the playbook runs.
        required: false
        default: None
    import_key:
        description:
            - Wether or not to import the created keyring into Ceph.
            This can be useful for someone that only wants to generate keyrings
            but not add them into Ceph.
        required: false
        default: True
    dest:
        description:
            - Destination to write the keyring
        required: false
        default: /etc/ceph/
    fetch_initial_keys:
        description:
            - Fetch client.admin and bootstrap key.
            This is only needed for Nautilus and above.
            Writes down to the filesystem the initial keys generated by the monitor.  # noqa E501
            This command can ONLY run from a monitor node.
        required: false
        default: false
'''

EXAMPLES = '''

keys_to_create:
  - { name: client.key, key: "AQAin8tUUK84ExAA/QgBtI7gEMWdmnvKBzlXdQ==", caps: { mon: "allow rwx", mds: "allow *" } , mode: "0600" } # noqa e501
  - { name: client.cle, caps: { mon: "allow r", osd: "allow *" } , mode: "0600" } # noqa e501

caps:
  mon: "allow rwx"
  mds: "allow *"

- name: create ceph admin key
  ceph_key:
    name: client.admin
    state: present
    secret: AQAin8tU2DsKFBAAFIAzVTzkL3+gtAjjpQiomw==
    caps:
      mon: allow *
      osd: allow *
      mgr: allow *
      mds: allow
    mode: 0400
    import_key: False

- name: create monitor initial keyring
  ceph_key:
    name: mon.
    state: present
    secret: AQAin8tUMICVFBAALRHNrV0Z4MXupRw4v9JQ6Q==
    caps:
      mon: allow *
    dest: "/var/lib/ceph/tmp/keyring.mon"
    import_key: False

- name: create cephx key
  ceph_key:
    name: "{{ keys_to_create }}"
    state: present
    caps: "{{ caps }}"

- name: create cephx key but don't import it in Ceph
  ceph_key:
    name: "{{ keys_to_create }}"
    state: present
    caps: "{{ caps }}"
    import_key: False

- name: update cephx key
  ceph_key:
    name: "my_key"
    state: update
    caps: "{{ caps }}"

- name: delete cephx key
  ceph_key:
    name: "my_key"
    state: absent

- name: info cephx key
  ceph_key:
    name: "my_key""
    state: info

- name: list cephx keys
  ceph_key:
    state: list

- name: fetch cephx keys
  ceph_key:
    state: fetch_initial_keys
'''

RETURN = '''#  '''

from ansible.module_utils.basic import AnsibleModule  # noqa E402
import datetime  # noqa E402
import grp  # noqa E402
import json  # noqa E402
import os  # noqa E402
import pwd  # noqa E402
import stat  # noqa E402
import struct  # noqa E402
import time  # noqa E402
import base64  # noqa E402
import socket  # noqa E402

CEPH_INITIAL_KEYS = ['client.admin', 'client.bootstrap-mds', 'client.bootstrap-mgr',  # noqa E501
                     'client.bootstrap-osd', 'client.bootstrap-rbd', 'client.bootstrap-rbd-mirror', 'client.bootstrap-rgw']  # noqa E501


def fatal(message, module):
    '''
    Report a fatal error and exit
    '''

    if module:
        module.fail_json(msg=message, rc=1)
    else:
        raise(Exception(message))


def generate_secret():
    '''
    Generate a CephX secret
    '''

    key = os.urandom(16)
    header = struct.pack('<hiih', 1, int(time.time()), 0, len(key))
    secret = base64.b64encode(header + key)

    return secret


def generate_caps(cmd, _type, caps):
    '''
    Generate CephX capabilities list
    '''

    for k, v in caps.items():
        # makes sure someone didn't pass an empty var,
        # we don't want to add an empty cap
        if len(k) == 0:
            continue
        if _type == "ceph-authtool":
            cmd.extend(["--cap"])
        cmd.extend([k, v])

    return cmd


def generate_ceph_cmd(cluster, args, user, user_key, containerized=None):
    '''
    Generate 'ceph' command line to execute
    '''

    cmd = []

    base_cmd = [
        'ceph',
        '-n',
        user,
        '-k',
        user_key,
        '--cluster',
        cluster,
        'auth',
    ]

    cmd.extend(base_cmd + args)

    if containerized:
        cmd = containerized.split() + cmd

    return cmd


def generate_ceph_authtool_cmd(cluster, name, secret, caps, auid, dest, containerized=None):  # noqa E501
    '''
    Generate 'ceph-authtool' command line to execute
    '''

    file_destination = os.path.join(
        dest + "/" + cluster + "." + name + ".keyring")

    cmd = [
        'ceph-authtool',
        '--create-keyring',
        file_destination,
        '--name',
        name,
        '--add-key',
        secret,
    ]

    cmd.extend(base_cmd)
    cmd = generate_caps(cmd, "ceph-authtool", caps)

    if containerized:
        cmd = containerized.split() + cmd

    return cmd


def create_key(module, result, cluster, name, secret, caps, import_key, auid, dest, containerized=None):  # noqa E501
    '''
    Create a CephX key
    '''

    file_path = os.path.join(dest + "/" + cluster + "." + name + ".keyring")

    args = [
        'import',
        '-i',
        file_path,
    ]
    cmd_list = []

    if not secret:
        secret = generate_secret()

    cmd_list.append(generate_ceph_authtool_cmd(
        cluster, name, secret, caps, dest, container_image))

    if import_key:
        user = "client.admin"
        user = "client.admin"
        user_key = os.path.join(
            "/etc/ceph/" + cluster + ".client.admin.keyring")
        cmd_list.append(generate_ceph_cmd(
            cluster, args, user, user_key, containerized))

    return cmd_list


def update_key(cluster, name, caps, containerized=None):
    '''
    Update a CephX key's capabilities
    '''

    cmd_list = []

    args = [
        'caps',
        name,
    ]

    args = generate_caps(args, "ceph", caps)
    user = "client.admin"
    user_key = os.path.join(
        "/etc/ceph/" + cluster + ".client.admin.keyring")
    cmd_list.append(generate_ceph_cmd(
        cluster, args, user, user_key, containerized))

    return cmd_list


def delete_key(cluster, name, containerized=None):
    '''
    Delete a CephX key
    '''

    cmd_list = []

    args = [
        'del',
        name,
    ]

    user = "client.admin"
    user_key = os.path.join(
        "/etc/ceph/" + cluster + ".client.admin.keyring")
    cmd_list.append(generate_ceph_cmd(
        cluster, args, user, user_key, containerized))

    return cmd_list


def info_key(cluster, name, user, user_key, output_format, containerized=None):
    '''
    Get information about a CephX key
    '''

    cmd_list = []

    args = [
        'get',
        name,
        '-f',
        output_format,
    ]

    cmd_list.append(generate_ceph_cmd(
        cluster, args, user, user_key, containerized))

    return cmd_list


def list_keys(cluster, user, user_key, containerized=None):
    '''
    List all CephX keys
    '''

    cmd_list = []

    args = [
        'ls',
        '-f',
        'json',
    ]

    cmd_list.append(generate_ceph_cmd(
        cluster, args, user, user_key, containerized))

    return cmd_list


def exec_commands(module, cmd_list):
    '''
    Execute command(s)
    '''

    for cmd in cmd_list:
        rc, out, err = module.run_command(cmd)
        if rc != 0:
            return rc, cmd, out, err

    return rc, cmd, out, err


def lookup_ceph_initial_entities(out):
    '''
    Lookup Ceph initial keys entries in the auth map
    '''

    # convert out to json, ansible returns a string...
    try:
        out_dict = json.loads(out)
    except ValueError as e:
        fatal("Could not decode 'ceph auth list' json output: {}".format(e), module)  # noqa E501

    entities = []
    if "auth_dump" in out_dict:
        for key in out_dict["auth_dump"]:
            for k, v in key.items():
                if k == "entity":
                    if v in CEPH_INITIAL_KEYS:
                        entities.append(v)
    else:
        fatal("'auth_dump' key not present in json output:", module)  # noqa E501

    if len(entities) != len(CEPH_INITIAL_KEYS):
        return None

    return entities


def build_key_path(cluster, entity):
    '''
    Build key path depending on the key type
    '''

    if "admin" in entity:
        path = "/etc/ceph"
        key_path = os.path.join(
            path + "/" + cluster + "." + entity + ".keyring")
    elif "bootstrap" in entity:
        path = "/var/lib/ceph"
        # bootstrap keys show up as 'client.boostrap-osd'
        # however the directory is called '/var/lib/ceph/bootstrap-osd'
        # so we need to substring 'client.'
        entity_split = entity.split('.')[1]
        key_path = os.path.join(
            path + "/" + entity_split + "/" + cluster + ".keyring")
    else:
        return None

    return key_path


def run_module():
    module_args = dict(
        cluster=dict(type='str', required=False, default='ceph'),
        name=dict(type='str', required=False),
        state=dict(type='str', required=True),
        containerized=dict(type='str', required=False, default=None),
        caps=dict(type='dict', required=False, default=None),
        secret=dict(type='str', required=False, default=None),
        import_key=dict(type='bool', required=False, default=True),
        dest=dict(type='str', required=False, default='/etc/ceph/'),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
        add_file_common_args=True,
    )

    # Gather module parameters in variables
    state = module.params['state']
    name = module.params.get('name')
    cluster = module.params.get('cluster')
    containerized = module.params.get('containerized')
    caps = module.params.get('caps')
    secret = module.params.get('secret')
    import_key = module.params.get('import_key')
    dest = module.params.get('dest')

    result = dict(
        changed=False,
        stdout='',
        stderr='',
        rc='',
        start='',
        end='',
        delta='',
    )

    if module.check_mode:
        return result

    startd = datetime.datetime.now()

    # Test if the key exists, if it does we skip its creation
    # We only want to run this check when a key needs to be added
    # There is no guarantee that any cluster is running and we don't need one
    if import_key:
        user = "client.admin"
        user_key = os.path.join(
            "/etc/ceph/" + cluster + ".client.admin.keyring")
        output_format = "json"
        rc, cmd, out, err = exec_commands(
            module, info_key(cluster, name, user, user_key, output_format, containerized))  # noqa E501

    if state == "present":
        if not caps:
            fatal("Capabilities must be provided when state is 'present'", module)  # noqa E501

        # We allow 'present' to override any existing key
        # ONLY if a secret is provided
        # if not we skip the creation
        if import_key:
            if rc == 0 and not secret:
                result["stdout"] = "skipped, since {0} already exists, if you want to update a key use 'state: update'".format(  # noqa E501
                    name)
                result['rc'] = rc
                module.exit_json(**result)

        rc, cmd, out, err = exec_commands(module, create_key(
            module, result, cluster, name, secret, caps, import_key, dest, container_image))  # noqa E501

        file_path = os.path.join(
            dest + "/" + cluster + "." + name + ".keyring")
        file_args = module.load_file_common_arguments(module.params)
        file_args['path'] = file_path
        module.set_fs_attributes_if_different(file_args, False)
    elif state == "update":
        if not caps:
            fatal("Capabilities must be provided when state is 'update'", module)  # noqa E501

        if rc != 0:
            result["stdout"] = "skipped, since {0} does not exist".format(name)
            result['rc'] = 0
            module.exit_json(**result)

        rc, cmd, out, err = exec_commands(
            module, update_key(cluster, name, caps, containerized))

    elif state == "absent":
        rc, cmd, out, err = exec_commands(
            module, delete_key(cluster, name, containerized))

    elif state == "info":
        if rc != 0:
            result["stdout"] = "skipped, since {0} does not exist".format(name)
            result['rc'] = 0
            module.exit_json(**result)

        user = "client.admin"
        user_key = os.path.join(
            "/etc/ceph/" + cluster + ".client.admin.keyring")
        output_format = "json"
        rc, cmd, out, err = exec_commands(
            module, info_key(cluster, name, user, user_key, output_format, containerized))  # noqa E501

    elif state == "list":
        user = "client.admin"
        user_key = os.path.join(
            "/etc/ceph/" + cluster + ".client.admin.keyring")
        rc, cmd, out, err = exec_commands(
            module, list_keys(cluster, user, user_key, containerized))

    elif state == "fetch_initial_keys":
        hostname = socket.gethostname()
        user = "mon."
        user_key = os.path.join(
            "/var/lib/ceph/mon/" + cluster + "-" + hostname + "/keyring")
        rc, cmd, out, err = exec_commands(
            module, list_keys(cluster, user, user_key, containerized))
        if rc != 0:
            result["stdout"] = "failed to retrieve ceph keys".format(name)
            result['rc'] = 0
            module.exit_json(**result)

        entities = lookup_ceph_initial_entities(out)
        if entities is None:
            fatal("Failed to find some of the initial entities", module)

        # get ceph's group and user id
        ceph_uid = pwd.getpwnam('ceph').pw_uid
        ceph_grp = grp.getgrnam('ceph').gr_gid

        output_format = "plain"
        for entity in entities:
            key_path = build_key_path(cluster, entity)
            if key_path is None:
                fatal("Failed to build key path, no entity yet?", module)
            elif os.path.isfile(key_path):
                # if the key is already on the filesystem
                # there is no need to fetch it again
                continue

            extra_args = [
                '-o',
                key_path,
            ]

            info_cmd = info_key(cluster, entity, user,
                                user_key, output_format, containerized)
            # we use info_cmd[0] because info_cmd is an array made of an array
            info_cmd[0].extend(extra_args)
            rc, cmd, out, err = exec_commands(
                module, info_cmd)  # noqa E501

            # apply ceph:ceph ownership and mode 0400 on keys
            try:
                os.chown(key_path, ceph_uid, ceph_grp)
                os.chmod(key_path, stat.S_IRUSR)
            except OSError as e:
                fatal("Failed to set owner/group/permissions of %s: %s" % (
                    key_path, str(e)), module)

    else:
        module.fail_json(
            msg='State must either be "present" or "absent" or "update" or "list" or "info" or "fetch_initial_keys".', changed=False, rc=1)  # noqa E501

    endd = datetime.datetime.now()
    delta = endd - startd

    result = dict(
        cmd=cmd,
        start=str(startd),
        end=str(endd),
        delta=str(delta),
        rc=rc,
        stdout=out.rstrip(b"\r\n"),
        stderr=err.rstrip(b"\r\n"),
        changed=True,
    )

    if rc != 0:
        module.fail_json(msg='non-zero return code', **result)

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
