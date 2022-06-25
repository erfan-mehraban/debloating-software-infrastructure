import os
import stat
from collections import defaultdict
import json
import tarfile
from tempfile import TemporaryDirectory

from allfiles import make_metadata, make_tree
from cppaudit import cppauparse, childparent_map, read_files
import straceparser

def prepare_audit_data(initpid):
    # get the audit data
    cppauparse(initpid)
    # get all descendents of initpid
    parchild = defaultdict(list)
    for child, parent in childparent_map.items():
        parchild[parent].append(child)

    # now get a transitive closure over the par-child relation
    def dfs_transclosure(pid):
        l = []
        for child in parchild[pid]:
            l.extend(dfs_transclosure(child))
        l.extend(parchild[pid])
        return l
    processes = dfs_transclosure(initpid)
    processes.append(initpid) # eases later processing

    # get all files read by processes
    files = set()
    for pid in processes:
        if pid in read_files:
            files |= read_files[pid]
    return files


def slim(img_name, new_name, files):
    ''' Remove redundant files from the image layers and prepare a new image. We
    expect the container is already run and logs collected.  The `initpid` is
    pid 1 of the container as seen in the root pid namespace.  '''
    # container config
    metadata = make_metadata(img_name, addid=True)
    newid = metadata['id']

    # get the image ready
    os.makedirs(os.path.join(new_name, newid))
    with open(os.path.join(new_name, 'repositories'), 'w') as f:
        json.dump({new_name: {'latest': newid}}, f)
    with open(os.path.join(new_name, newid, 'VERSION'), 'w') as f:
        f.write('1.0') # anything should work
    with open(os.path.join(new_name, newid, 'json'), 'w') as f:
        json.dump(metadata, f)

    added_files = set()
    def taradd(tree, tar, path):
        path = os.path.normpath(path)
        if path in added_files:
            return False
        try:
            res = os.lstat(path)
        except FileNotFoundError:
            return False
        # recursively add parent directories
        parent = os.path.dirname(path)
        stack = [] # we will do a recursion here
        while parent not in added_files and parent != tree:
            stack.append(parent)
            parent = os.path.dirname(parent)
        for parent in reversed(stack):
            # tar archives conventionally have trailing dir / so adding one
            tar.add(parent, recursive=False,
                    arcname=os.path.relpath(parent, start=tree)+'/')
            added_files.add(parent)
        # now add the real path
        arcname = os.path.relpath(path, start=tree)
        if stat.S_ISDIR(res.st_mode):
            tar.add(path, recursive=False, arcname=arcname+'/')
        else:
            tar.add(path, arcname=arcname)
        added_files.add(path)
        return True

    # add layer.tar
    with TemporaryDirectory(prefix='cpp') as tree:
        make_tree(img_name, tree)
        print('tree done', tree)
        with tarfile.TarFile(os.path.join(new_name, newid, 'layer.tar'),
                mode='w') as tar:
            for name in files:
                # we will remove the leading hash to make paths relative to tar
                path = os.path.join(tree, name[1:])
                added = taradd(tree, tar, path)
                while added and os.path.islink(path):
                    newpath = os.readlink(path)
                    if os.path.isabs(newpath):
                        arcname = newpath[1:]
                        path = os.path.join(tree, arcname)
                    else:
                        path = os.path.join(os.path.dirname(path), newpath)
                        arcname = os.path.relpath(path, tree)
                    if arcname not in files:
                        added = taradd(tree, tar, path)
                    else: # we will add it in as part of upper loop
                        break
        print('layer.tar done')

    # finally, tar everything for docker load
    with tarfile.TarFile(new_name + '.tar', mode='w') as tar:
        tar.add(os.path.join(new_name, newid), arcname=newid)
        tar.add(os.path.join(new_name, 'repositories'), arcname='repositories')

def main(img_name, new_name, initpid, trace=None):
    ## audit-based slimming
    #files = prepare_audit_data(initpid)

    # ptrace-based slimming
    files = straceparser.existing_files(initpid, trace)

    # some files are implicitly needed for execve of ELF binaries
    files.update(['/lib/ld-linux.so.2', '/lib64/ld-linux-x86-64.so.2'])
    print(files)

    slim(img_name, new_name, files)
