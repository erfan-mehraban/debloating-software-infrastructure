import os
import sys
import stat
from collections import defaultdict
import json
import tarfile
from tempfile import TemporaryDirectory
import mmap
import subprocess 
import shlex
import shutil
from itertools import combinations

import arrow

import utils
import allfiles
import straceparser


# we can make this function more efficient by reducing the # of mmaps
def reduce_environ(files, envkeys):
    envkeys = {bytes(key, 'utf-8') for key in envkeys}
    not_accessed = set(envkeys)
    for file in files:
        with open(file, 'rb') as f:
            contents = f.read()
            not_accessed -= {key for key in not_accessed if key in contents}
    envkeys = envkeys - not_accessed
    return {key.decode('utf-8') for key in envkeys}


def make_img_metadata():
    img_metadata = json.loads(allfiles.configtemplate)
    allfiles.addid(img_metadata)
    img_metadata['created'] = str(arrow.utcnow())
    return img_metadata

def make_img_skeleton(name, numlayers, ismain, oldimg):
    layerid = None
    layerids = []
    for i in range(numlayers):
        metadata = make_img_metadata()
        if layerid:
            metadata['parent'] = layerid
        layerid = metadata['id']
        if ismain:
            allfiles.copy_img_metadata(oldimg, metadata)
        layerids.append(layerid)
        os.makedirs(os.path.join(name, layerid))
        with open(os.path.join(name, layerid, 'VERSION'), 'w') as f:
            f.write('1.0') # anything should work
        with open(os.path.join(name, layerid, 'json'), 'w') as f:
            json.dump(metadata, f)
    with open(os.path.join(name, 'repositories'), 'w') as f:
        json.dump({name: {'latest': layerid}}, f)
    layers = [os.path.join(name, layerid, 'layer.tar') for layerid in layerids]
    return name, layers

def make_img_tar(name, imgdir):
    # finally, tar everything for docker load
    with tarfile.TarFile(name, mode='w') as tar:
        for filename in os.listdir(imgdir):
            tar.add(os.path.join(imgdir, filename), arcname=filename)

# we will use normpath, even though it may not be accurate
# assume path has no leading '/'. As such, due to the way this function is
# written, it behaves as if the path is first stripped of its leading '/'
def rooted_realpath(path, tree):
    original = os.path.normpath(path)
    components = original.split('/')
    path = ''
    for component in components:
        path = os.path.join(path, component)
        fullpath = os.path.join(tree, path) 
        if os.path.islink(fullpath):
            newpath = os.readlink(fullpath)
            if os.path.isabs(newpath):
                path = newpath[1:]
            else:
                path = os.path.join(os.path.dirname(path), newpath)
    return path


def add_links_and_parents(tree, paths):
    paths = list(paths) # make a local copy of paths to modify
    paths_with_parents = set() # docker does not allow redundant paths
    for path in paths:
        original = path
        ancestor_paths = []
        while path: # our paths are relative so final dirname will be ''
            # print(path)
            ancestor_paths.append(path)
            dirname = os.path.dirname(path)
            fullpath = os.path.join(tree, path)
            if os.path.islink(fullpath):
                # clear descendents, which should be accessed from realpath
                ancestor_paths = [path]
                newpath = os.readlink(fullpath)
                if os.path.isabs(newpath):
                    newpath = newpath[1:]
                else:
                    newpath = os.path.join(dirname, newpath)
                if os.path.lexists(os.path.join(tree, newpath)):
                    paths.append(os.path.normpath(newpath))
                    # graft the descendent path onto newpath
                    # our paths are normpath'ed so this is a bit easier
                    if path != original:
                        graft = os.path.relpath(original, path)
                        paths.append(os.path.normpath(os.path.join(newpath,
                            graft)))
            path = dirname
        paths_with_parents.update(ancestor_paths)
    # make paths sorted
    return sorted(paths_with_parents)

# Python's tar implementation is too slow, so we added a new implementation
# based on the tar utility (compatible with both BSD and GNU tar)
def make_layer_tar(name, tree, paths, stubexe, stubpaths, exepath, executorpath):
    name = os.path.abspath(name)

    # normalize stubpaths and exepath
    # os.path.normpath is not needed because 
    stubpaths = [rooted_realpath(p, tree) for p in stubpaths]
    exepath = rooted_realpath(exepath, tree)

    # add the main tree
    # we will use a list of files to add from tree. We will also explicitly add
    # parent dirs to the list. We will also recursively add all symlinks
    paths_with_parents = add_links_and_parents(tree, paths)
    # filter out the stubpaths that will be added later
    paths_w_pars_filtered = [p for p in paths_with_parents if p not in
            stubpaths]
    with utils.tmpfilename() as tfname:
        with open(tfname, 'w') as f:
            for path in paths_w_pars_filtered:
                f.write('{}\n'.format(path))
        cmd = 'tar -cf {} --no-recursion -T {}'.format(name, tfname)
        subprocess.check_call(shlex.split(cmd), cwd=tree)

    # add executorexe and sockdirs for stubs and executors
    with utils.tmpdirname() as dname:
        dir_fd = os.open(dname, os.O_RDONLY)
        os.mkdir('walls', dir_fd=dir_fd)
        for path in stubpaths:
            path = os.path.normpath(path)
            sockdir = os.path.join('walls', path.replace('/', '_'))
            os.mkdir(sockdir, dir_fd=dir_fd)
            os.chmod(sockdir, 0o777, dir_fd=dir_fd)
        sockdir = os.path.join('walls', exepath.replace('/', '_'))
        os.mkdir(sockdir, dir_fd=dir_fd)
        os.chmod(sockdir, 0o777, dir_fd=dir_fd)
        os.link(executorpath, 'walls/wexec', dst_dir_fd=dir_fd)
        cmd = 'tar rf {} *'.format(name)
        subprocess.check_call(cmd, cwd=dname, shell=True)

    # we need some more manipulation to add stubpaths that tar utility does not
    # provide
    stubexesize = os.stat(stubexe).st_size
    with tarfile.open(name, 'a') as tf:
        for path in stubpaths:
            fullpath = os.path.join(tree, path)
            ti = tf.gettarinfo(fullpath, path)
            ti.size = stubexesize
            with open(stubexe, 'rb') as f:
                tf.addfile(ti, f)


def make_volume(name, tree, paths):
    print('make_volume', name, tree, paths)
    name = os.path.abspath(name)
    paths = add_links_and_parents(tree, paths)
    with utils.tmpfilename() as tfname:
        with open(tfname, 'w') as f:
            for path in paths:
                f.write('{}\n'.format(path))
        cmd = 'tar c -T {} | tar x -C {}'.format(tfname, name)
        subprocess.check_call(cmd, shell=True, cwd=tree)

def make_volume_all_paths(name, tree):
    name = os.path.abspath(name)
    try:
        os.makedirs(name)
    except:
        return
    cmd = 'tar c . | tar x -C {}'.format(name)
    subprocess.check_call(cmd, shell=True, cwd=tree)


def make_stub_layer(name, tree, stubexe, paths):
    ''' create a layer containing the stub exes that communicate with other
    containers running actual exes. Assume that paths have first slash
    removed. Here is what we do here: copy the dir part of the paths with the
    same metadata, then the actual exe into the dir part of path and copy the
    metadata, and moreover creating and changing the permissions of the socket
    dirs'''
    name = os.path.abspath(name)
    with utils.tmpdirname() as dname:
        dir_fd = os.open(dname, os.O_RDONLY)
        os.mkdir('walls', dir_fd=dir_fd)
        for path in paths:
            path = os.path.normpath(path)
            dirname = os.path.dirname(path)
            pathcopycmd = 'tar c {} -C {} | tar x -C {}'.format(
                    dirname, tree, dname)
            subprocess.check_call(pathcopycmd, shell=True)
            os.link(stubexe, path, dst_dir_fd=dir_fd)
            shutil.copystat(os.path.join(tree, path), os.path.join(dname,
                path))
            st = os.stat(os.path.join(tree, path))
            os.chown(os.path.join(dname, path), st.st_uid, st.st_gid)
            sockdir = os.path.join('walls', path.replace('/', '_'))
            os.mkdir(sockdir, dir_fd=dir_fd)
            os.chmod(sockdir, 0o777, dir_fd=dir_fd)
        cmd = 'tar cf {} *'.format(name)
        subprocess.check_call(cmd, cwd=dname, shell=True)

def make_executor_layer(name, path, executorexe):
    ''' this is for the executor or the stalk that receives the graft '''
    name = os.path.abspath(name)
    with utils.tmpdirname() as dname:
        dir_fd = os.open(dname, os.O_RDONLY)
        os.mkdir('walls', dir_fd=dir_fd)
        sockdir = os.path.join('walls', path.replace('/', '_'))
        os.mkdir(sockdir, dir_fd=dir_fd)
        os.chmod(sockdir, 0o777, dir_fd=dir_fd)
        os.link(executorexe, 'walls/wexec', dst_dir_fd=dir_fd)
        cmd = 'tar cf {} *'.format(name)
        subprocess.check_call(cmd, cwd=dname, shell=True)


# TODO this does not work correctly with symlinks linking to absolute paths
# e.g., /lib64/ld-linux-x86-64.so.2
def file_isreg(path):
    ''' tell whether path is a regular file or a link ultimately leading to a
    regular file '''
    try:
        res = os.stat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(res.st_mode)

def isancestor(ancpath, despath):
    if ancpath[-1] == '/':
        ancpath = ancpath[:-1]
    return despath.startswith(ancpath) and (len(despath) == len(ancpath) or
            despath[len(ancpath)] == '/')

def reduce_volumes(files, volumes):
    def vol_accessed(vol):
        for file in files:
            if isancestor(vol, file):
                return True
        return False
    red_vols = list(filter(vol_accessed, volumes))
    return red_vols

def lexisting_ancestors(tree, paths):
    for p in paths:
        while p: # p is relative
            if os.path.lexists(os.path.join(tree, p)):
                yield p
                break
            p = os.path.dirname(p)


def make_container(name, tree, ismain, oldimg, files, envkeys, cntnr_metadata, selfexepath,
        exepaths, stubexe, executorexe):
    print(name)
    # we will remove the leading slash to make paths relative to tar
    paths = [file[1:] for file in files]
    # filter to keep only existing paths
    ## paths = [p for p in paths if os.path.lexists(os.path.join(tree, p))]
    paths = set(lexisting_ancestors(tree, paths))

    # remove the leading slash to make exepaths relative; filter out the
    # selfexe. Remove leading hash for selfexepath also
    exepaths = [path[1:] for path in exepaths if path != selfexepath]
    selfexepath = selfexepath[1:]
    imgdir, layertars = make_img_skeleton(name, 1, ismain, oldimg)
    make_layer_tar(layertars[0], tree, paths, stubexe, exepaths, selfexepath,
            executorexe)
    #make_stub_layer(layertars[1], tree, stubexe, exepaths)
    #make_executor_layer(layertars[2], selfexepath, executorexe)
    make_img_tar(name+'.tar', imgdir)

    # TODO we are not yet checking env vars that may be accessed from mounted
    #   volumes
    reg_files = filter(file_isreg, [os.path.join(tree, p) for
        p in paths])
    reduced_envkeys = reduce_environ(reg_files, envkeys)
    #print(reduced_envkeys)
    
    volumes = cntnr_metadata['Mounts']
    reduced_vol_dests = reduce_volumes(files,
            [vol['Destination'] for vol in volumes])
    reduced_volumes = [vol for vol in volumes if vol['Destination'] in
            reduced_vol_dests]
    print(reduced_volumes)

    return reduced_envkeys, reduced_volumes, cntnr_metadata['Config']['WorkingDir']

def remove_dynamic_paths(paths):
    dynroots = ['/dev', '/proc', '/sys']
    return [p for p in paths if not any((p.startswith(x) for x in dynroots))] 

def interpreter(path):
    try:
        with open(path, 'rb') as f:
            if f.read(2) == b'#!':
                return f.readline().decode('utf-8').split(None, maxsplit=1)[0]
    except FileNotFoundError:
        # check if file is a link: absolute links will be evaluated to the host
        # root and may not be found
        if os.path.islink(path):
            # TODO: this is not the right handling; we should evaluate the link
            # ourselves or do some chroot in another process
            return None
        raise

linkers = ['/lib/ld-linux.so.2',
        '/lib64/ld-linux-x86-64.so.2',
        '/lib/ld-musl-x86_64.so.1'] # last one is on alpine
class Context(object):
    def __init__(self, tree, execrec, ismain=False):
        self.tree = tree
        # no need for argv, children, cwd
        # keep keys only for env
        self.exe = execrec.exe # the first exe is kind of an ID for the object
        self.exes = [execrec.exe]
        #print(execrec.envp)
        self.envkeys = {kv.split('=', maxsplit=1)[0] for kv in execrec.envp}
        self.exist_files = set(execrec.exist_files)
        self.exist_files.update(linkers) # linker files are read implicitly
        interp = interpreter(os.path.join(self.tree, execrec.exe[1:]))
        if interp:
            self.exist_files.add(interp)
        self.written_files = set(execrec.written_files)
        self.connects = list(execrec.connects)
        self.binds = list(execrec.binds)
        self.exec_files = {execrec.exec_file} if execrec.exec_file else set()
        self.ismain = ismain

    def merge(self, execrec, addexe=False):
        # assume self.exe == execrec.exe
        if addexe:
            self.exes.append(execrec.exe)
        self.envkeys.update((kv.split('=', maxsplit=1)[0] for kv in
            execrec.envp))
        self.exist_files.update(execrec.exist_files)
        interp = interpreter(os.path.join(self.tree, execrec.exe[1:]))
        if interp:
            self.exist_files.add(interp)
        self.written_files.update(execrec.written_files)
        self.connects.extend(execrec.connects)
        self.binds.extend(execrec.binds)
        if execrec.exec_file:
            self.exec_files.add(execrec.exec_file)

    def normpaths(self):
        self.exes = set(map(os.path.normpath, self.exes))
        self.exist_files = map(os.path.normpath, self.exist_files)
        self.written_files = map(os.path.normpath, self.written_files)
        self.exist_files = set(remove_dynamic_paths(self.exist_files))
        self.written_files = set(remove_dynamic_paths(self.written_files))
        # not normalization but very important
        self.exec_files = set(map(os.path.normpath, self.exec_files)) - self.exes
        print(self.exes)
        print(self.exec_files)
        #print(self.exist_files)

def tovolpath(path, tree):
    return rooted_realpath(path[1:], tree).replace('/', '_')

# a context function returns (rec, exec_vols, stubpaths) pairs
def allonecontext(pid_records):
    exec_records = [rec for pidrec in pid_records.values() for rec in
            pidrec.exec_records]
    # merge records based on rec.exe.
    merged_record = Context(exec_records[0], ismain=True)
    for rec in exec_records[1:]:
        merged_record.merge(rec)
    merged_record.normpaths()
    # for this kind of context, there is only one context and no stubs, vols
    return [merged_record], [[]], [[]]

def oneonecontext(pid_records, rootpid):
    mainexe = pid_records[rootpid][0].exe
    exec_records = [rec for pidrec in pid_records.values() for rec in
            pidrec.exec_records]
    # merge all records
    merged_records = dict()
    for rec in exec_records:
        if rec.exe in merged_records:
            merged_records[rec.exe].merge(rec)
        else:
            merged_records[rec.exe] = Context(rec)
    merged_records[mainexe].ismain = True
    exec_records = list(merged_records.values())
    for rec in exec_records:
        rec.normpaths()
    exec_vols = [[execpath for execpath
        in rec.exec_files | rec.exes] for rec in exec_records]
    exec_vols = zip(exec_vols, exec_vols)
    stubs = [rec.exec_files for rec in exec_records]
    return exec_records, exec_vols, stubs

def manyonecontext(pid_records, rootpid, policy, tree):
    print(policy)
    contexts = {} # ctxtid (int) -> context
    exe2context = {} # exe -> ctxtid
    for ctxtid, exes in enumerate(policy):
        for exe in exes:
            exe2context[exe] = ctxtid
    def dfs_make_rec(pidrec, context=None):
        for rec in pidrec.exec_records:
            if rec.exe in exe2context:
                if exe2context[rec.exe] not in contexts:
                    ismain = context is None
                    contexts[exe2context[rec.exe]] = Context(tree, rec, ismain=ismain)
                else:
                    contexts[exe2context[rec.exe]].merge(rec, addexe=True)
                context = contexts[exe2context[rec.exe]]
            else:
                if not context:
                    contexts[ctxtid+1] = Context(tree, rec, ismain=True)
                    context = contexts[ctxtid+1]
                else:
                    context.merge(rec)
            for child, _ in rec.children:
                dfs_make_rec(pid_records[child], context)
    dfs_make_rec(pid_records[rootpid])
    exec_recs = list(contexts.values())
    for ctxt in exec_recs:
        ctxt.normpaths()
    stubs = [{f for f in rec.exec_files if f in exe2context} for rec in
            exec_recs]
    def exec_vol(ctxt):
        for f in ctxt.exec_files:
            if f in exe2context:
                ctxt2 = contexts[exe2context[f]]
                yield (ctxt2.exe, f)
        selfexevol = ctxt.exe
        yield (selfexevol, selfexevol)
    exec_vols = [list(exec_vol(ctxt)) for ctxt in exec_recs]
    return exec_recs, exec_vols, stubs
                


def socket_connections(exec_records):
    unix_binds = {}
    ip_binds = {}
    binds = {}
    unix_connections = defaultdict(set)
    net_connections = set()
    for rec in exec_records:
        for bind in rec.binds:
            if bind['family'] == 'AF_LOCAL':
                binds[(bind['sun_path'], bind.get('abstract'))] = rec.exe
                if not bind.get('abstract'):
                    rec.exist_files.add(bind['sun_path']) # this is just like files
                    rec.written_files.add(bind['sun_path']) # this is just like files
            elif bind['family'] == 'AF_INET' or bind['family'] == 'AF_INET6':
                binds[bind['port']] = (rec.exe, bind['addr'])

    for rec in exec_records:
        for connect in rec.connects:
            if connect['family'] == 'AF_LOCAL':
                # We are not handling abstract sockets..., a socket is going to
                # be assumed non-abstract
                if (connect['sun_path'], connect.get('abstract')) in binds:
                    unix_connections[frozenset((rec.exe, binds[(connect['sun_path'],
                        connect.get('abstract'))]))].add(connect['sun_path'])
                    if not bind.get('abstract'):
                        rec.exist_files.add(connect['sun_path']) # this is just like files
                        rec.written_files.add(connect['sun_path']) # this is just like files
            elif connect['family'] == 'AF_INET' or connect['family'] == 'AF_INET6':
                if connect['port'] in binds and utils.islocalhost(connect['addr']):
                    net_connections.add((rec.exe, binds[connect['port']][0]))

    print(unix_connections)
    print(net_connections)
    return unix_connections, net_connections

def lisdir(path):
    ''' tell whether path is a regular file or a link ultimately leading to a
    regular file '''
    try:
        res = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(res.st_mode)


class shared_volumes:
    def __init__(self, recs, unix_connections, tree, orig_vols, volpath):
        self.recs = recs
        self.unix_connections = unix_connections
        self.tree = tree
        self.orig_vols = orig_vols
        self.volpath = volpath
        self.vols = defaultdict(set)
        self.replaced = {}

    def __call__(self):
        self.make_pair_vols()
        self.remove_children()
        self.remove_orig_vols()
        self.replace_symlink_mountpoints()
        self.make_content()
        return self.vols

    def existing_parents(self, dirs):
        newdirs = set()
        for d in dirs:
            d = d[1:]
            while d:
                path = os.path.join(self.tree, d)
                # allow symlinks to be vol points; we will resolve the symlinks
                # soon
                if os.path.isdir(path): 
                    newdirs.add('/'+d)
                    break
                d = os.path.dirname(d)
            else:
                raise Exception('Sharing impossible')
        return newdirs

    def sv(self, rec1, rec2):
        r1andw2 = rec1.exist_files & rec2.written_files
        w1andr2 = rec1.written_files & rec2.exist_files
        unixrw = self.unix_connections.get(frozenset((rec1.exe, rec2.exe)), set())
        # we will try sharing the parent directories for r1w2 and w1r2 cases.
        # For each file in these sets, we need to consider if another file rooted
        # in the same parent has been accessed and exists in the original tree. If
        # yes, since this parent was not originally a volume, the contents of the
        # new volume should include the older contents

        # not sure why next three lines were put here
        # for file in r1andw2 | w1andr2:
        #     dir = os.path.dirname(file)
        #     return dir

        # TODO see if this is correct in presence of symlinks
        dirs = {os.path.dirname(f) for f in r1andw2 | w1andr2 | unixrw}
        volumes = self.existing_parents(dirs)
        return volumes

    def make_pair_vols(self):
        for rec1, rec2 in combinations(self.recs, 2):
            vols = self.sv(rec1, rec2)
            print(rec1.exe, rec2.exe, vols)
            for vol in vols:
                self.vols[vol].update((rec1, rec2))

    def remove_children(self):
        print(list(self.vols.keys()))
        toremove = set()
        for v1, v2 in combinations(self.vols, 2):
            if v1.startswith(v2+'/'):
                self.vols[v2].update(self.vols[v1])
                toremove.add(v1)
            elif v2.startswith(v1+'/'):
                self.vols[v1].update(self.vols[v2])
                toremove.add(v2)
        for v in toremove:
            del self.vols[v]

    def remove_orig_vols(self):
        for v in self.orig_vols:
            v = os.path.normpath(v)
            for vol in list(self.vols.keys()):
                if vol.startswith(v + '/') or vol == v:
                    del self.vols[vol]

    def replace_symlink_mountpoints(self):
        print(list(self.vols.keys()))
        for vol in self.vols:
            print(vol)
            subtree = os.path.join(self.tree, vol[1:])
            changed = False
            while os.path.islink(subtree):
                print(subtree)
                newpath = os.readlink(subtree)
                if os.path.isabs(newpath):
                    newpath = newpath[1:]
                else:
                    newpath = os.path.join(subtree, newpath)
                subtree = os.path.normpath(os.path.join(self.tree, newpath))
                changed = True
            if changed:
                newvol = '/' + os.path.relpath(subtree, self.tree)
                self.vols[newvol] = self.vols[vol]
                del self.vols[vol]
                self.replaced[newvol] = vol

    def make_content(self):
        for vol, recs in self.vols.items():
            prefix = self.replaced.get(vol, vol)
            paths = {f for rec in recs for f in rec.exist_files}
            subtree = os.path.join(self.tree, prefix[1:])
            stripchars = len(prefix + '/')
            paths = [p[stripchars:] for p in paths if p.startswith(prefix +
                '/')]
            # note: if we replace the first arg below by prefix, it will
            # resolve abspath symlinks with respect to host; we don't want this
            paths = set(lexisting_ancestors(os.path.join(self.tree, vol[1:]), paths))
            print('make_content', vol, prefix, paths)
            cmd = 'tar c --no-recursion {} | tar x -C {}'.format(vol[1:],
                    self.volpath)
            subprocess.check_call(cmd, shell=True, cwd=self.tree)
            volname = os.path.join(self.volpath, vol[1:])
            make_volume(volname, os.path.join(self.tree, vol[1:]), paths)

            # for f in r1orr2:
            #     if (f != file and f.startswith(dir + '/') and
            #             os.path.lexists(os.path.join(tree, f[1:])):
            #         print(rec1.exe, rec2.exe, 'not separable', file=sys.stderr)
            #         print('read-write', file, 'together with', f, file=sys.stderr)
            #         return False

def make_exec_vol(src, dst, volpath):
    srcpath = os.path.join(volpath, 'walls', src)
    os.makedirs(srcpath, exist_ok=True)
    return {'Destination': os.path.join('/walls', dst), 'Source': srcpath}

def fmt_shared_vols(vols, volpath):
    return [{
        'Destination': vol,
        'Source': os.path.join(volpath, vol[1:])
        } for vol in vols]

def partition(oldimg, newimgprefix, cntnr, rootpid, traces_prefix, stubexe,
        executorexe, volpath):
    cntnr_metadata = allfiles.cntnr_metadata(cntnr)
    pid_records = straceparser.process(rootpid, traces_prefix,
            cntnr_metadata['Config']['WorkingDir'])
    print({rec.exe for pidrec in pid_records.values() for rec in
            pidrec.exec_records})
    # import pdb; pdb.set_trace()

    with open('policy.json') as f:
        policy = json.load(f)

    orig_vol_paths = [vol['Destination'] for vol in cntnr_metadata['Mounts']]
    config = {}

    with utils.tmpdirname() as tree:
        allfiles.make_tree(oldimg, tree)
        print('tree done')

        #exec_records = oneonecontext(pid_records)
        exec_records, exec_vols_s, stubs_s = manyonecontext(pid_records,
                rootpid, policy, tree)
        #exec_records, exec_vols_s, stubs_s = allonecontext(pid_records)
        print(len(exec_records))

        unix_connections, net_connections = socket_connections(exec_records)

        # we do not need unix_connections to be passed into shared_volumes now
        # because we are already adding the socket file to exist_files
        shared_vols = shared_volumes(exec_records, unix_connections, tree, orig_vol_paths,
                volpath)()
        shared_vols_rev = defaultdict(set)
        for v, recs in shared_vols.items():
            for rec in recs:
                shared_vols_rev[rec].add(v)
        for rec, exec_vols, stubs in zip(exec_records, exec_vols_s, stubs_s):
            dirname, basename = os.path.split(rec.exe)
            newcntnrname = '{}_{}_{}'.format(newimgprefix,
                    os.path.basename(dirname), basename)
            cntnrconfig = {}
            config[newcntnrname] = cntnrconfig
            envkeys, vols, wd = make_container(newcntnrname, tree, rec.ismain,
                    oldimg, rec.exist_files, rec.envkeys, cntnr_metadata,
                    rec.exe, stubs, stubexe, executorexe)
            print(stubs)
            cntnrconfig['envkeys'] = list(envkeys)
            for vol in vols:
                if vol['Source'].startswith('/var/lib/docker/volumes'):
                    src = os.path.join(volpath, vol['Destination'][1:])
                    vol['Source'] = src
                    subtree = os.path.join(tree, vol['Destination'][1:])
                    make_volume_all_paths(src, subtree)
            cntnrconfig['vols'] = list(vols)
            cntnrconfig['wd'] = wd
            # get volumes for shared files. We're toast if more than 2
            # containers share a file.
            cntnrconfig['shared_vols'] = fmt_shared_vols(shared_vols_rev[rec],
                    volpath)
            cntnrconfig['exec_vols'] = [make_exec_vol(tovolpath(src, tree),
                    tovolpath(dst, tree), volpath) for src, dst in exec_vols]
            cntnrconfig['cmd'] = '/walls/wexec /' + rooted_realpath(rec.exe[1:],
                    tree)
            cntnrconfig['ismain'] = rec.ismain

    with open('{}.json'.format(newimgprefix), 'w') as f:
        json.dump({ 'config': config, 'original_container': cntnr_metadata }, f)

if __name__ == '__main__':
    partition(*sys.argv[1:])
